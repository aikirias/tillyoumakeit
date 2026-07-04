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

Cross-column **correlation** is not imposed here — ``generate_marginals`` treats
columns independently. The numeric sampler is driven by a single uniform per row
(``numeric_from_uniform``), so Story 2.2's Gaussian copula can inject *correlated*
uniforms through ``generate_faithful`` (``tymi.synth.generator``) while reusing the
exact same marginal inverse-CDF.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from tymi.core.errors import GenerationError
from tymi.domain.artifacts import (
    ColumnProfile,
    Dataset,
    DatetimeStats,
    LogicalType,
    NumericStats,
    Profile,
    TextStats,
)
from tymi.synth.conditions import Condition, Equals, Members

#: Alphabet used to synthesize placeholder free-text content (length-faithful only).
_TEXT_ALPHABET = np.array(list("abcdefghijklmnopqrstuvwxyz"))


class MarginalSynthesizer:
    """Synthesizer that reproduces each column's marginal distribution.

    Structurally satisfies the ``tymi.ports.Synthesizer`` Protocol.
    """

    def generate(self, profile: Profile, *, rows: int, rng: np.random.Generator) -> Dataset:
        return generate_marginals(profile, rows=rows, rng=rng)


def generate_marginals(profile: Profile, *, rows: int, rng: np.random.Generator) -> Dataset:
    """Generate ``rows`` synthetic rows matching ``profile``'s per-column marginals.

    Columns are independent (no correlation). Correlation preservation composes
    this via ``tymi.synth.generator.generate_faithful`` (Story 2.2).
    """
    return synthesize(profile, rows=rows, rng=rng, uniforms=None)


def synthesize(
    profile: Profile,
    *,
    rows: int,
    rng: np.random.Generator,
    uniforms: dict[str, np.ndarray] | None = None,
    conditions: dict[str, Condition] | None = None,
) -> Dataset:
    """Assemble the Dataset column-by-column, optionally injecting driven uniforms.

    ``uniforms`` maps a column name to a pre-drawn ``[0, 1]`` vector used for that
    (numeric) column's inverse-CDF — the Gaussian copula supplies correlated
    uniforms here; unmapped columns draw independently.

    ``conditions`` maps a column name to a :class:`~tymi.synth.conditions.Condition`
    (Story 2.4). A conditioned column is generated under its restriction with **no
    nulls** so 100% of rows satisfy the predicate; every other column is unchanged.
    """
    if rows < 0:
        raise ValueError(f"rows must be >= 0, got {rows}")
    uniforms = uniforms or {}
    conditions = conditions or {}

    profiles_by_name = {c.name: c for c in profile.columns}
    # Drive column order from the canonical Schema when present, else from the
    # profiled columns; the two are built in the same order by the profiler.
    ordered = list(profile.schema.columns) or None
    names = [c.name for c in ordered] if ordered else [c.name for c in profile.columns]

    data = {}
    for name in names:
        cp = profiles_by_name.get(name)
        if cp is None:
            # A schema column with no profiled statistics cannot be conditioned
            # (we have no type/stats to restrict it) — fail loudly instead of
            # silently emitting an all-null column that ignores the condition.
            if name in conditions:
                raise GenerationError(
                    f"cannot apply a condition to column {name!r}: "
                    "no profiled statistics available for it"
                )
            data[name] = pd.Series([None] * rows, dtype=object)
            continue
        data[name] = _generate_column(
            cp, rows, rng, uniform=uniforms.get(name), condition=conditions.get(name)
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


def _generate_column(
    cp: ColumnProfile,
    rows: int,
    rng: np.random.Generator,
    *,
    uniform: np.ndarray | None = None,
    condition: Condition | None = None,
    inject_nulls: bool = True,
) -> pd.Series:
    """Build one synthetic column as a pandas Series with a Schema-consistent dtype.

    ``uniform`` (shape ``(rows,)``, values in ``[0, 1]``) drives the numeric
    inverse-CDF when supplied — the Gaussian copula passes *correlated* uniforms
    here; otherwise the numeric column draws its own independent uniform.

    ``condition`` (Story 2.4) restricts this column's sampler so every row
    satisfies it; a conditioned column carries **no nulls**.

    ``inject_nulls`` (Story 2.5) is set ``False`` by the leakage gate's resampler so
    a regenerated cell is never a NULL — a NULL never collides, so injecting one
    would silently "resolve" a collision by nulling the cell instead of replacing it.
    """
    if condition is not None:
        return _conditioned_column(cp, rows, rng, condition, uniform)

    mask = _null_mask(cp, rows, rng) if inject_nulls else np.zeros(rows, dtype=bool)

    # Dispatch on the stats actually present (a STRING column may carry either
    # category labels or length stats), falling back to all-null.
    if cp.count == 0:
        pass  # all-null; each branch below is skipped via the final fallback
    elif cp.numeric is not None:
        integer = cp.logical_type == LogicalType.INTEGER
        u = rng.random(rows) if uniform is None else np.asarray(uniform, dtype=float)
        return _numeric_series(numeric_from_uniform(cp.numeric, u), mask, integer=integer)
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


def resample_column(
    cp: ColumnProfile,
    rows: int,
    rng: np.random.Generator,
    *,
    condition: Condition | None = None,
) -> pd.Series:
    """Draw ``rows`` fresh independent values for one column (Story 2.5 gate).

    Used by the leakage gate to regenerate colliding cells: it mirrors the marginal
    sampler (optionally under a Story 2.4 ``condition``) with an independent draw —
    the copula's correlation is not re-imposed on a handful of replaced cells. Never
    injects a NULL (a NULL would spuriously "resolve" a collision without replacing
    the real value), so the gate either finds a clean value or fails closed.
    """
    return _generate_column(cp, rows, rng, condition=condition, inject_nulls=False)


# --- conditioned sampling (Story 2.4) -------------------------------------


def _conditioned_column(
    cp: ColumnProfile,
    rows: int,
    rng: np.random.Generator,
    condition: Condition,
    uniform: np.ndarray | None,
) -> pd.Series:
    """Generate a column restricted by ``condition`` (no nulls, 100% satisfaction)."""
    if isinstance(condition, Equals):
        return _constant_column(cp, rows, condition.value)
    if isinstance(condition, Members):
        return _members_column(cp, rows, rng, condition.values)
    return _between_column(cp, rows, rng, condition.low, condition.high, uniform)


def _constant_column(cp: ColumnProfile, rows: int, value: str) -> pd.Series:
    """A length-``rows`` constant column typed by ``cp.logical_type``."""
    lt = cp.logical_type
    if lt == LogicalType.INTEGER:
        return pd.Series(pd.array([_coerce_int(value, cp.name)] * rows, dtype="Int64"))
    if lt == LogicalType.FLOAT:
        return pd.Series([_coerce_number(value, cp.name)] * rows, dtype="float64")
    if lt == LogicalType.BOOLEAN:
        return pd.Series(pd.array([_coerce_bool(value, cp.name)] * rows, dtype="boolean"))
    if lt == LogicalType.DATETIME:
        ts = _coerce_ts(value, cp.name)
        return _datetime_series(pd.Series([ts] * rows), np.zeros(rows, dtype=bool))
    return pd.Series(np.array([str(value)] * rows, dtype=object), dtype=object)


def _members_column(
    cp: ColumnProfile, rows: int, rng: np.random.Generator, values: tuple[str, ...]
) -> pd.Series:
    """Draw only from ``values`` (renormalized categorical freq when available)."""
    lt = cp.logical_type
    if lt == LogicalType.INTEGER:
        ints = np.array([_coerce_int(v, cp.name) for v in values], dtype="int64")
        picked = ints[rng.integers(0, ints.size, size=rows)]
        return pd.Series(pd.array(picked, dtype="Int64"))
    if lt == LogicalType.FLOAT:
        nums = np.array([_coerce_number(v, cp.name) for v in values], dtype=float)
        picked = nums[rng.integers(0, nums.size, size=rows)]
        return pd.Series(picked, dtype="float64")
    if lt == LogicalType.BOOLEAN:
        bools = [_coerce_bool(v, cp.name) for v in values]
        picked = [bools[i] for i in rng.integers(0, len(bools), size=rows)]
        return pd.Series(pd.array(picked, dtype="boolean"))
    if lt == LogicalType.DATETIME:
        stamps = [_coerce_ts(v, cp.name) for v in values]
        picked = [stamps[i] for i in rng.integers(0, len(stamps), size=rows)]
        return _datetime_series(pd.Series(picked), np.zeros(rows, dtype=bool))
    return _members_categorical(cp, rows, rng, values)


def _members_categorical(
    cp: ColumnProfile, rows: int, rng: np.random.Generator, values: tuple[str, ...]
) -> pd.Series:
    """Categorical/text membership: keep the source proportions among allowed labels.

    Uses add-one (Laplace) smoothing so a label the user explicitly requested is
    still generated even when it is unseen or outside the profiled top-K (a raw
    proportional weight would floor it to zero); seen labels keep ~their share.
    """
    allowed = list(dict.fromkeys(values))  # de-duplicate, preserve order
    by_value = (
        {str(c.value): float(c.count) for c in cp.categories} if cp.categories is not None else {}
    )
    counts = np.array([by_value.get(str(v), 0.0) for v in allowed], dtype=float)
    weights = (counts + 1.0) / (counts.sum() + len(allowed))
    idx = rng.choice(len(allowed), size=rows, p=weights)
    return pd.Series(np.array([allowed[i] for i in idx], dtype=object), dtype=object)


def _between_column(
    cp: ColumnProfile,
    rows: int,
    rng: np.random.Generator,
    low: str,
    high: str,
    uniform: np.ndarray | None,
) -> pd.Series:
    """Restrict a numeric/datetime column to an inclusive ``[low, high]`` range."""
    if cp.logical_type == LogicalType.DATETIME:
        return _between_datetime(cp, rows, rng, low, high)
    lo = _coerce_number(low, cp.name)
    hi = _coerce_number(high, cp.name)
    if hi < lo:
        lo, hi = hi, lo
    u = rng.random(rows) if uniform is None else np.asarray(uniform, dtype=float)
    stats = cp.numeric
    if stats is None:
        values = lo + u * (hi - lo)
    else:
        c_lo = _cdf_at(stats, max(lo, stats.min))
        c_hi = _cdf_at(stats, min(hi, stats.max))
        if c_hi <= c_lo:
            # The requested range carries no observed mass (disjoint or a spike at a
            # single bin edge) → fall back to a uniform across the requested range.
            values = lo + u * (hi - lo)
        else:
            values = numeric_from_uniform(stats, c_lo + u * (c_hi - c_lo))
    values = np.clip(values, lo, hi)
    if cp.logical_type == LogicalType.INTEGER:
        int_lo = np.ceil(lo)
        int_hi = np.floor(hi)
        if int_lo > int_hi:
            raise GenerationError(
                f"range condition on integer column {cp.name!r} contains no integer: "
                f"[{low}, {high}]"
            )
        ints = np.clip(np.rint(values), int_lo, int_hi).astype("int64")
        return pd.Series(pd.array(ints, dtype="Int64"))
    return pd.Series(np.asarray(values, dtype=float), dtype="float64")


def _between_datetime(
    cp: ColumnProfile, rows: int, rng: np.random.Generator, low: str, high: str
) -> pd.Series:
    """Uniform datetime sampling across ``[low, high]`` intersected with observed."""
    lo = _coerce_ts(low, cp.name)
    hi = _coerce_ts(high, cp.name)
    if hi < lo:
        lo, hi = hi, lo
    stats = cp.datetime
    s_lo, s_hi = lo, hi
    if stats is not None and stats.min is not None and stats.max is not None:
        obs_lo, obs_hi = pd.Timestamp(stats.min), pd.Timestamp(stats.max)
        clipped_lo, clipped_hi = max(lo, obs_lo), min(hi, obs_hi)
        if clipped_lo <= clipped_hi:  # keep the intersection; else sample full range
            s_lo, s_hi = clipped_lo, clipped_hi
    lo_i, hi_i = pd.Timestamp(s_lo).value, pd.Timestamp(s_hi).value
    if hi_i <= lo_i:
        draws = np.full(rows, lo_i, dtype="int64")
    else:
        draws = np.clip((lo_i + rng.random(rows) * (hi_i - lo_i)).astype("int64"), lo_i, hi_i)
    return _datetime_series(pd.to_datetime(draws), np.zeros(rows, dtype=bool))


def _cdf_at(stats: NumericStats, x: float) -> float:
    """Piecewise-linear histogram CDF at ``x`` (exact inverse of ``numeric_from_uniform``)."""
    edges = np.asarray(stats.histogram_bins, dtype=float)
    counts = np.asarray(stats.histogram_counts, dtype=float)
    total = counts.sum()
    if edges.size < 2 or total <= 0:
        if stats.max <= stats.min:
            return 0.0
        return float(np.clip((x - stats.min) / (stats.max - stats.min), 0.0, 1.0))
    if x <= edges[0]:
        return 0.0
    if x >= edges[-1]:
        return 1.0
    probs = counts / total
    cdf = np.concatenate([[0.0], np.cumsum(probs)])
    cdf[-1] = 1.0
    i = int(np.clip(np.searchsorted(edges, x, side="right") - 1, 0, probs.size - 1))
    span = edges[i + 1] - edges[i]
    frac = 0.0 if span <= 0 else (x - edges[i]) / span
    return float(cdf[i] + frac * probs[i])


def _coerce_number(value: str, column: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        raise GenerationError(
            f"condition value {value!r} for column {column!r} is not numeric"
        ) from None


def _coerce_int(value: str, column: str) -> int:
    """Coerce a condition value to an int, rejecting non-integral input (AC-2)."""
    number = _coerce_number(value, column)
    if number != int(number):
        raise GenerationError(
            f"condition value {value!r} for integer column {column!r} is not a whole number"
        )
    return int(number)


_TRUE_LITERALS = frozenset({"true", "1", "t", "yes", "y"})
_FALSE_LITERALS = frozenset({"false", "0", "f", "no", "n"})


def _coerce_bool(value: str, column: str) -> bool:
    """Coerce a condition value to a bool, rejecting unrecognized literals."""
    token = str(value).strip().lower()
    if token in _TRUE_LITERALS:
        return True
    if token in _FALSE_LITERALS:
        return False
    raise GenerationError(
        f"condition value {value!r} for boolean column {column!r} is not a boolean"
    )


def _coerce_ts(value: str, column: str) -> pd.Timestamp:
    try:
        ts = pd.Timestamp(value)
    except (TypeError, ValueError):
        raise GenerationError(
            f"condition value {value!r} for column {column!r} is not a datetime"
        ) from None
    if ts is pd.NaT:
        raise GenerationError(f"condition value {value!r} for column {column!r} is not a datetime")
    return ts


# --- per-type samplers ----------------------------------------------------


def numeric_from_uniform(stats: NumericStats, uniform: np.ndarray) -> np.ndarray:
    """Exact piecewise-linear inverse-CDF of the histogram, evaluated at ``uniform``.

    Each bin is treated as uniform density; the CDF is piecewise-linear over the
    bin edges. Mapping a uniform ``u ∈ [0, 1]`` through this inverse-CDF reproduces
    the histogram's marginal shape from a *single* uniform per row — which lets the
    Gaussian copula supply correlated uniforms without changing the marginal.
    Values are clamped to the stored ``[min, max]``.
    """
    edges = np.asarray(stats.histogram_bins, dtype=float)
    counts = np.asarray(stats.histogram_counts, dtype=float)
    u = np.asarray(uniform, dtype=float)
    total = counts.sum()
    if edges.size < 2 or total <= 0:
        # Degenerate histogram: fall back to a uniform across the observed range.
        return np.clip(stats.min + u * (stats.max - stats.min), stats.min, stats.max)
    probs = counts / total
    cdf = np.concatenate([[0.0], np.cumsum(probs)])
    cdf[-1] = 1.0  # guard against floating-point drift at the top edge
    # Bin index for each u: the last edge whose cumulative prob is <= u.
    idx = np.clip(np.searchsorted(cdf, u, side="right") - 1, 0, probs.size - 1)
    span = cdf[idx + 1] - cdf[idx]  # == probs[idx]; 0 only for empty bins
    nonzero = span > 0
    frac = np.zeros_like(u)
    frac[nonzero] = (u[nonzero] - cdf[idx][nonzero]) / span[nonzero]
    values = edges[idx] + frac * (edges[idx + 1] - edges[idx])
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
