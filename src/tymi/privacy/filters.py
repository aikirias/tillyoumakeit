"""Privacy filters over faithful output (Story 4.2).

Two filters drop synthetic rows that pose a privacy risk, keeping the canonical Schema:

- :class:`SimilarityFilter` — drops any row closer than ``threshold`` (a mixed-type
  normalized distance) to *any* row of the real ``reference`` sample, so no output row
  sits suspiciously close to a real record.
- :class:`OutlierFilter` — drops rows with a numeric value beyond ``threshold`` standard
  deviations of the generated column — the tail where memorization of real extreme
  values concentrates.

Both take the real ``reference`` explicitly (AD-6: the Profile stores no raw values, so
distance-to-real is a connected-pipeline concern). They **drop** rows (no re-draw), so
the filtered output is deterministic (AD-4/AD-11 trivially: no randomness).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from tymi.domain.artifacts import Dataset, LogicalType

_NUMERIC = frozenset({LogicalType.INTEGER, LogicalType.FLOAT})


class SimilarityFilter:
    """Drop output rows within ``threshold`` of a real reference row."""

    def __init__(self, threshold: float = 0.1, *, enabled: bool = True) -> None:
        # Guard here too, not only in PrivacyConfig: a caller may build the filter directly.
        # threshold 0 is a filter-enabled no-op (every distance is >= 0) that would silently
        # keep exact real-record copies, and a negative threshold keeps everything.
        if threshold <= 0:
            raise ValueError(f"threshold must be > 0, got {threshold}")
        self.threshold = threshold
        self.enabled = enabled

    def filter(self, dataset: Dataset, *, reference: Dataset) -> Dataset:
        if not self.enabled or dataset.frame.empty or reference.frame.empty:
            return dataset
        distances = nearest_reference_distance(dataset, reference)
        keep = distances >= self.threshold
        return Dataset(frame=dataset.frame[keep].reset_index(drop=True), schema=dataset.schema)


class OutlierFilter:
    """Drop output rows whose numeric value is an extreme (memorization-prone) outlier."""

    def __init__(self, threshold: float = 4.0, *, enabled: bool = True) -> None:
        # A negative threshold flags every finite row (z > negative is always true) and
        # would empty the frame; guard directly, not only via PrivacyConfig.
        if threshold <= 0:
            raise ValueError(f"threshold must be > 0, got {threshold}")
        self.threshold = threshold
        self.enabled = enabled

    def filter(self, dataset: Dataset, *, reference: Dataset | None = None) -> Dataset:
        if not self.enabled or dataset.frame.empty:
            return dataset
        frame = dataset.frame
        numeric_cols = [
            c.name
            for c in dataset.schema.columns
            if c.logical_type in _NUMERIC and c.name in frame.columns
        ]
        is_outlier = np.zeros(len(frame), dtype=bool)
        for name in numeric_cols:
            values = pd.to_numeric(frame[name], errors="coerce").to_numpy(dtype=float)
            finite = values[np.isfinite(values)]
            if finite.size < 2:
                continue
            # Robust (median/MAD) z-score, not mean/std: a cluster of memorized extremes
            # inflates the std and masks itself (``[0]*100 + [1e6]*20`` escapes a mean/std
            # filter). MAD collapses to 0 when >50% of values are identical, so fall back
            # to the mean absolute deviation, which still has spread. Both use the standard
            # consistency scaling so the threshold stays in familiar "sigma" units.
            median = np.median(finite)
            mad = np.median(np.abs(finite - median))
            if mad > 0:
                z = np.abs(0.6745 * (values - median) / mad)
            else:
                mean_ad = np.mean(np.abs(finite - median))
                if mean_ad == 0:
                    continue
                z = np.abs(0.7979 * (values - median) / mean_ad)
            is_outlier |= np.nan_to_num(z, nan=0.0) > self.threshold
        keep = ~is_outlier
        return Dataset(frame=frame[keep].reset_index(drop=True), schema=dataset.schema)


#: Cap the generated-row block so peak memory is ``_CHUNK x n_ref`` floats, not
#: ``n_gen x n_ref`` — the pairwise distance matrix is otherwise quadratic and a large
#: output frame would OOM (5000x5000x3col already peaks ~880MB).
_CHUNK = 2048


def nearest_reference_distance(dataset: Dataset, reference: Dataset) -> np.ndarray:
    """Per generated row, the minimum mixed-type normalized distance to any reference row.

    Numeric columns are z-scored by the reference's per-column std (so the threshold is
    scale-free); a categorical/text mismatch contributes 1. Distance is Euclidean over
    those normalized components. Generated rows are processed in blocks of ``_CHUNK`` so
    the pairwise matrix never materializes for the whole output at once.
    """
    common = [c for c in dataset.schema.columns if c.name in reference.frame.columns]
    gen = dataset.frame
    ref = reference.frame
    n_gen, n_ref = len(gen), len(ref)
    if n_gen == 0 or n_ref == 0:
        return np.full(n_gen, np.inf)
    if not common:
        # Fail loud: with no shared column there is nothing to measure closeness against,
        # and silently returning "infinitely far" would keep every row and disable the
        # privacy filter under the guise of success (a false sense of privacy).
        raise ValueError(
            "nearest_reference_distance: dataset and reference share no columns; "
            "cannot measure similarity"
        )

    # Precompute each reference column once, reused per block. For a categorical column we
    # carry (values-with-nulls-neutralised, null-mask) so null semantics are decided by the
    # masks below (a raw string sentinel is fragile: pandas ``str`` vs ``object`` dtypes
    # round-trip a null-byte marker differently, so two nulls could miscompare).
    ref_cols: list[tuple[bool, np.ndarray, float, np.ndarray]] = []
    for column in common:
        name = column.name
        if column.logical_type in _NUMERIC:
            r = pd.to_numeric(ref[name], errors="coerce").to_numpy(dtype=float)
            std = np.nanstd(r[~np.isnan(r)]) if np.isfinite(r).any() else 0.0
            ref_cols.append((True, r, std if std > 0 else 1.0, np.isnan(r)))
        else:
            r_null = ref[name].isna().to_numpy()
            r = ref[name].where(~ref[name].isna(), "").astype(object).to_numpy()
            ref_cols.append((False, r, 1.0, r_null))

    out = np.empty(n_gen, dtype=float)
    for start in range(0, n_gen, _CHUNK):
        block = gen.iloc[start : start + _CHUNK]
        sq = np.zeros((len(block), n_ref), dtype=float)
        for column, (is_numeric, r, scale, r_null) in zip(common, ref_cols, strict=True):
            name = column.name
            if is_numeric:
                g = pd.to_numeric(block[name], errors="coerce").to_numpy(dtype=float)
                diff = (g[:, None] - r[None, :]) / scale
                d2 = diff**2
                g_null = np.isnan(g)
            else:
                g_null = block[name].isna().to_numpy()
                g = block[name].where(~block[name].isna(), "").astype(object).to_numpy()
                d2 = (g[:, None] != r[None, :]).astype(float)
            # Null-aware for both column kinds: both-null → 0 (two missing values match, so
            # a memorized copy sharing a null is NOT pushed past the threshold and leaked);
            # exactly one null → a 1.0 mismatch. The "" filler / raw diff is only reached
            # for the both-present cells the masks leave untouched.
            gn, rn = g_null[:, None], r_null[None, :]
            sq += np.where(gn & rn, 0.0, np.where(gn | rn, 1.0, d2))
        out[start : start + len(block)] = np.sqrt(sq).min(axis=1)
    return out
