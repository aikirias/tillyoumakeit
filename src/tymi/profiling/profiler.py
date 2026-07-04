"""Per-column statistical profiler (Story 1.6).

Turns a ``Dataset`` (DataFrame + Schema) into a ``Profile`` of per-column
aggregates. AD-6: no raw row values are stored — numeric summaries, low-cardinality
category labels (documented assumption), and free-text length stats only.
"""

from __future__ import annotations

import secrets
from collections.abc import Sequence

import numpy as np
import pandas as pd

from tymi.core.errors import ConfigError
from tymi.domain.artifacts import (
    CategoryFrequency,
    ColumnProfile,
    Dataset,
    DatetimeStats,
    LeakageGuard,
    LogicalType,
    NumericStats,
    Profile,
    TextStats,
    leakage_digest,
)
from tymi.privacy.classifier import classify_sensitive_columns
from tymi.profiling.correlations import detect_correlations

_QUANTILES = (0.05, 0.25, 0.5, 0.75, 0.95)

#: A STRING column is only stored as categorical (labels kept) when its values
#: are short; longer values are treated as free text so raw content is not
#: materialized (AD-6). Robust PII suppression lands in Epic 4.
_MAX_CATEGORICAL_VALUE_LENGTH = 64


def profile_dataset(
    dataset: Dataset,
    *,
    top_k: int = 20,
    categorical_threshold: int = 50,
    histogram_bins: int = 10,
    sensitive_columns: Sequence[str] = (),
    not_sensitive_columns: Sequence[str] = (),
    classify_pii: bool = False,
    min_match_rate: float = 0.5,
    salt: str | None = None,
) -> Profile:
    """Profile every column of a Dataset according to its logical type.

    ``sensitive_columns`` (Story 2.5) are hashed into a :class:`LeakageGuard` so the
    downstream leakage gate can prove no real sensitive value leaks — a declared
    column absent from the table raises :class:`ConfigError`. ``salt`` overrides the
    auto-generated per-Profile nonce (tests pass a fixed value for reproducibility).

    ``classify_pii`` (Story 4.1) auto-detects Sensitive Columns from the sample; the
    final sensitive set is ``(auto ∪ sensitive_columns) − not_sensitive_columns``, so
    the config can mark a missed column or unmark a false positive.
    """
    if histogram_bins < 1:
        raise ValueError(f"histogram_bins must be >= 1, got {histogram_bins}")
    frame = dataset.frame
    detected = (
        classify_sensitive_columns(dataset, min_match_rate=min_match_rate) if classify_pii else {}
    )
    # ``not_sensitive_columns`` only UNMARKS auto-detected false positives — an explicit
    # ``sensitive_columns`` mark always wins (unmarking it would silently disable a
    # security control the user deliberately set).
    excluded = set(not_sensitive_columns) - set(sensitive_columns)
    kept = [c for c in detected if c not in excluded]
    combined = list(dict.fromkeys([*kept, *sensitive_columns]))
    # Build the guard first: it validates the declared columns and is the source of
    # truth for which columns must have their raw labels suppressed (AD-6).
    guard = build_leakage_guard(dataset, combined, salt=salt)
    sensitive = set(guard.columns) if guard is not None else set()
    columns = tuple(
        _profile_column(
            frame[col.name],
            col.logical_type,
            col.name,
            top_k=top_k,
            categorical_threshold=categorical_threshold,
            histogram_bins=histogram_bins,
            is_sensitive=col.name in sensitive,
        )
        for col in dataset.schema.columns
    )
    correlations = detect_correlations(
        frame, columns, max_categorical_cardinality=categorical_threshold
    )
    return Profile(
        schema=dataset.schema,
        row_count=int(len(frame)),
        columns=columns,
        correlations=correlations,
        leakage_guard=guard,
    )


def build_leakage_guard(
    dataset: Dataset, sensitive_columns: Sequence[str], *, salt: str | None = None
) -> LeakageGuard | None:
    """Hash each declared sensitive column's distinct real values (AD-6/AD-7).

    Returns ``None`` when no sensitive columns are declared. Each column must exist
    in the Schema (else :class:`ConfigError`); only its distinct non-null values are
    hashed with :func:`leakage_digest`, so the guard is a membership set carrying no
    raw values. ``salt`` defaults to a fresh per-Profile security nonce.
    """
    requested = list(dict.fromkeys(sensitive_columns))  # de-dup, keep order
    if not requested:
        return None
    known = set(dataset.schema.names())
    unknown = [c for c in requested if c not in known]
    if unknown:
        raise ConfigError(
            f"sensitive column(s) not found in the source table: {unknown}"
        )
    resolved_salt = salt if salt is not None else secrets.token_hex(16)
    frame = dataset.frame
    # Hash the raw non-null values (not a pre-stringified column): ``leakage_digest``
    # applies ``str()`` per element, exactly as the gate does when it hashes a
    # generated value. Pre-``.astype(str)`` here would diverge for datetimes
    # ("2020-06-15" vs "2020-06-15 00:00:00") and silently miss a real leak.
    columns = {
        name: tuple(sorted({leakage_digest(v, resolved_salt) for v in frame[name].dropna()}))
        for name in requested
    }
    return LeakageGuard(salt=resolved_salt, columns=columns)


def _profile_column(
    series: pd.Series,
    logical_type: LogicalType,
    name: str,
    *,
    top_k: int,
    categorical_threshold: int,
    histogram_bins: int,
    is_sensitive: bool = False,
) -> ColumnProfile:
    non_null = series.dropna()
    count = int(non_null.shape[0])
    null_count = int(series.isna().sum())
    distinct_count = int(non_null.nunique())
    base = {
        "name": name,
        "logical_type": logical_type,
        "count": count,
        "null_count": null_count,
        "distinct_count": distinct_count,
    }
    if count == 0:
        return ColumnProfile(**base)

    # A sensitive column must never persist its real values anywhere in the Profile
    # (AD-6 escalated): not category labels, and not numeric/datetime min/max/quantiles
    # (order statistics ARE two real row values). A free-text STRING keeps length stats
    # only so generation still yields typed synthetic/Faker strings; every other type
    # keeps counts only → a typed null column. Faithful synthesis of sensitive numbers,
    # dates and labels is deferred to Epic 4; the output leakage gate (AD-7) already
    # guarantees no real value is emitted for any type.
    if is_sensitive:
        if logical_type == LogicalType.STRING:
            return ColumnProfile(**base, text=_text_stats(non_null))
        return ColumnProfile(**base)

    if logical_type in (LogicalType.INTEGER, LogicalType.FLOAT):
        # numeric may be None if the column holds no finite numeric values
        return ColumnProfile(**base, numeric=_numeric_stats(non_null, histogram_bins))
    if logical_type == LogicalType.DATETIME:
        return ColumnProfile(**base, datetime=_datetime_stats(non_null))
    if logical_type in (LogicalType.CATEGORICAL, LogicalType.BOOLEAN):
        return ColumnProfile(**base, categories=_category_frequencies(non_null, top_k))
    # STRING: store labels only when low-cardinality AND short (AD-6); otherwise
    # keep length stats only so raw free-text content is never materialized.
    if distinct_count <= categorical_threshold and _values_are_short(non_null):
        return ColumnProfile(**base, categories=_category_frequencies(non_null, top_k))
    return ColumnProfile(**base, text=_text_stats(non_null))


def _values_are_short(series: pd.Series) -> bool:
    return bool(series.astype(str).str.len().max() <= _MAX_CATEGORICAL_VALUE_LENGTH)


def _numeric_stats(series: pd.Series, histogram_bins: int) -> NumericStats | None:
    values = pd.to_numeric(series, errors="coerce").to_numpy(dtype=float)
    values = values[np.isfinite(values)]  # drop NaN and +/-inf (histogram needs finite)
    if values.size == 0:
        return None
    counts, edges = np.histogram(values, bins=histogram_bins)
    std = float(np.std(values, ddof=1)) if values.size > 1 else 0.0
    return NumericStats(
        min=float(values.min()),
        max=float(values.max()),
        mean=float(values.mean()),
        std=std,
        quantiles={f"{int(q * 100)}": float(np.quantile(values, q)) for q in _QUANTILES},
        histogram_bins=tuple(float(e) for e in edges),
        histogram_counts=tuple(int(c) for c in counts),
    )


def _category_frequencies(series: pd.Series, top_k: int) -> tuple[CategoryFrequency, ...]:
    # Stringify *before* counting so a mixed-dtype object column (e.g. 1 and "1"
    # from a driver) does not emit two categories that both serialize to "1" with
    # split counts; labels are stored as strings anyway.
    counts = series.astype(str).value_counts()
    # deterministic: highest count first, ties broken by value
    ordered = sorted(counts.items(), key=lambda kv: (-int(kv[1]), str(kv[0])))[:top_k]
    return tuple(CategoryFrequency(value=str(v), count=int(c)) for v, c in ordered)


def _datetime_stats(series: pd.Series) -> DatetimeStats:
    dt = pd.to_datetime(series, errors="coerce").dropna()
    if dt.empty:
        return DatetimeStats(min=None, max=None, day_of_week_frequency={}, month_frequency={})
    dow = dt.dt.dayofweek.value_counts()
    month = dt.dt.month.value_counts()
    return DatetimeStats(
        min=dt.min().isoformat(),
        max=dt.max().isoformat(),
        day_of_week_frequency={str(int(k)): int(dow[k]) for k in sorted(dow.index)},
        month_frequency={str(int(k)): int(month[k]) for k in sorted(month.index)},
    )


def _text_stats(series: pd.Series) -> TextStats:
    lengths = series.astype(str).str.len()
    return TextStats(
        min_length=int(lengths.min()),
        max_length=int(lengths.max()),
        mean_length=float(lengths.mean()),
    )
