"""Marginal distribution synthesis (Story 2.1).

The first faithful-generation stage: given a ``Profile``, draw ``rows`` rows whose
*per-column* (marginal) distribution matches the Profile —

* numeric via inverse-transform sampling from the stored histogram,
* categorical/boolean from the stored top-K frequencies,
* datetime uniformly across the observed ``[min, max]`` range,
* free text as synthetic placeholder content whose length falls in the observed
  ``[min_length, max_length]`` range.

All randomness is drawn from the injected ``rng`` (AD-4/AD-11): the same seed
yields byte-identical output. AD-6 holds — only Profile aggregates are consumed,
never raw values; free text is regenerated, not reproduced. The output Dataset
carries the Profile's canonical ``Schema`` unchanged (AD-10).

Cross-column **correlation** is NOT preserved here — columns are independent.
Correlation preservation is Story 2.2 (in-house Gaussian copula).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from tymi.domain.artifacts import (
    ColumnProfile,
    Dataset,
    DatetimeStats,
    LogicalType,
    NumericStats,
    Profile,
    TextStats,
)

#: Alphabet used to synthesize placeholder free-text content (length-faithful only).
_TEXT_ALPHABET = np.array(list("abcdefghijklmnopqrstuvwxyz"))


class MarginalSynthesizer:
    """Synthesizer that reproduces each column's marginal distribution.

    Structurally satisfies the ``tymi.ports.Synthesizer`` Protocol.
    """

    def generate(self, profile: Profile, *, rows: int, rng: np.random.Generator) -> Dataset:
        return generate_marginals(profile, rows=rows, rng=rng)


def generate_marginals(profile: Profile, *, rows: int, rng: np.random.Generator) -> Dataset:
    """Generate ``rows`` synthetic rows matching ``profile``'s per-column marginals."""
    if rows < 0:
        raise ValueError(f"rows must be >= 0, got {rows}")

    profiles_by_name = {c.name: c for c in profile.columns}
    # Drive column order from the canonical Schema when present, else from the
    # profiled columns; the two are built in the same order by the profiler.
    ordered = list(profile.schema.columns) or None
    names = [c.name for c in ordered] if ordered else [c.name for c in profile.columns]

    data = {}
    for name in names:
        cp = profiles_by_name.get(name)
        data[name] = (
            _generate_column(cp, rows, rng)
            if cp is not None
            else pd.Series([None] * rows, dtype=object)
        )

    frame = pd.DataFrame(data, columns=names, index=range(rows))
    return Dataset(frame=frame, schema=profile.schema)


def _null_mask(cp: ColumnProfile, rows: int, rng: np.random.Generator) -> np.ndarray:
    """Boolean mask of positions that should be NULL, at the observed null rate."""
    if cp.count == 0:
        return np.ones(rows, dtype=bool)  # all-null column stays all-null
    total = cp.count + cp.null_count
    null_prob = cp.null_count / total if total else 0.0
    if null_prob <= 0:
        return np.zeros(rows, dtype=bool)
    return rng.random(rows) < null_prob


def _generate_column(cp: ColumnProfile, rows: int, rng: np.random.Generator) -> pd.Series:
    """Build one synthetic column as a pandas Series with a Schema-consistent dtype."""
    mask = _null_mask(cp, rows, rng)

    # Dispatch on the stats actually present (a STRING column may carry either
    # category labels or length stats), falling back to all-null.
    if cp.count == 0:
        pass  # all-null; each branch below is skipped via the final fallback
    elif cp.numeric is not None:
        integer = cp.logical_type == LogicalType.INTEGER
        return _numeric_series(_sample_numeric(cp.numeric, rows, rng), mask, integer=integer)
    elif cp.categories is not None:
        labels = _sample_categorical(cp, rows, rng)
        if cp.logical_type == LogicalType.BOOLEAN:
            return _boolean_series(labels, mask)
        return _categorical_series(labels, mask)
    elif cp.datetime is not None:
        return _datetime_series(_sample_datetime(cp.datetime, rows, rng), mask)
    elif cp.text is not None:
        return _categorical_series(_sample_text(cp.text, rows, rng), mask)

    # No usable stats (all-null column, or numeric column with no finite values).
    return pd.Series([None] * rows, dtype=object)


# --- per-type samplers ----------------------------------------------------


def _sample_numeric(stats: NumericStats, rows: int, rng: np.random.Generator) -> np.ndarray:
    """Inverse-transform sampling from the stored histogram, clamped to [min, max]."""
    edges = np.asarray(stats.histogram_bins, dtype=float)
    counts = np.asarray(stats.histogram_counts, dtype=float)
    total = counts.sum()
    if edges.size < 2 or total <= 0:
        # Degenerate histogram: fall back to uniform across the observed range.
        values = stats.min + rng.random(rows) * (stats.max - stats.min)
    else:
        probs = counts / total
        bins = rng.choice(counts.size, size=rows, p=probs)
        lo = edges[bins]
        hi = edges[bins + 1]
        values = lo + rng.random(rows) * (hi - lo)
    return np.clip(values, stats.min, stats.max)


def _sample_categorical(cp: ColumnProfile, rows: int, rng: np.random.Generator) -> list[object]:
    """Draw labels from the stored (top-K) category frequencies, renormalized."""
    labels = [c.value for c in cp.categories]
    counts = np.asarray([c.count for c in cp.categories], dtype=float)
    total = counts.sum()
    if not labels or total <= 0:
        return [None] * rows
    probs = counts / total
    idx = rng.choice(len(labels), size=rows, p=probs)
    return [labels[i] for i in idx]


def _sample_datetime(stats: DatetimeStats, rows: int, rng: np.random.Generator) -> pd.Series:
    """Uniform sampling across the observed [min, max] datetime range."""
    if stats.min is None or stats.max is None:
        return pd.Series([pd.NaT] * rows, dtype="datetime64[ns]")
    lo = pd.Timestamp(stats.min).value
    hi = pd.Timestamp(stats.max).value
    if hi <= lo:
        draws = np.full(rows, lo, dtype="int64")
    else:
        # float64 cannot represent nanosecond epochs exactly; clamp so a draw can
        # never round just past the observed bounds (matches the numeric clip).
        draws = np.clip((lo + rng.random(rows) * (hi - lo)).astype("int64"), lo, hi)
    return pd.to_datetime(draws)


def _sample_text(stats: TextStats, rows: int, rng: np.random.Generator) -> list[object]:
    """Synthetic placeholder strings with lengths drawn within [min, max] length."""
    lo = max(int(stats.min_length), 0)
    hi = max(int(stats.max_length), lo)
    lengths = rng.integers(lo, hi + 1, size=rows) if hi > lo else np.full(rows, lo)
    return ["".join(rng.choice(_TEXT_ALPHABET, size=int(length))) for length in lengths]


# --- series assembly (dtype + null injection) -----------------------------


def _numeric_series(values: np.ndarray, mask: np.ndarray, *, integer: bool) -> pd.Series:
    if integer:
        ints = np.rint(values).astype("int64")
        arr = pd.array(ints, dtype="Int64")
        arr[mask] = pd.NA
        return pd.Series(arr)
    floats = np.asarray(values, dtype=float).copy()
    floats[mask] = np.nan
    return pd.Series(floats, dtype="float64")


def _categorical_series(values: list[object], mask: np.ndarray) -> pd.Series:
    arr = np.array(values, dtype=object)
    arr[mask] = None
    return pd.Series(arr, dtype=object)


def _boolean_series(values: list[object], mask: np.ndarray) -> pd.Series:
    """Reconstruct a nullable boolean column from stringified category labels.

    A BOOLEAN column is profiled through the categorical path, so its labels are
    strings (``"True"``/``"False"``); map them back to real booleans so the frame
    dtype matches the Schema's declared BOOLEAN logical type (AD-10).
    """
    mapped = [pd.NA if v is None else _to_bool(v) for v in values]
    arr = pd.array(mapped, dtype="boolean")
    arr[mask] = pd.NA
    return pd.Series(arr)


def _to_bool(value: object) -> bool:
    return str(value).strip().lower() in {"true", "1", "t", "yes", "y"}


def _datetime_series(values: pd.Series, mask: np.ndarray) -> pd.Series:
    series = pd.Series(pd.to_datetime(values)).reset_index(drop=True)
    series[mask] = pd.NaT
    return series
