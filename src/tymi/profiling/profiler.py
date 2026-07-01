"""Per-column statistical profiler (Story 1.6).

Turns a ``Dataset`` (DataFrame + Schema) into a ``Profile`` of per-column
aggregates. AD-6: no raw row values are stored — numeric summaries, low-cardinality
category labels (documented assumption), and free-text length stats only.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from tymi.domain.artifacts import (
    CategoryFrequency,
    ColumnProfile,
    Dataset,
    DatetimeStats,
    LogicalType,
    NumericStats,
    Profile,
    TextStats,
)

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
) -> Profile:
    """Profile every column of a Dataset according to its logical type."""
    frame = dataset.frame
    columns = tuple(
        _profile_column(
            frame[col.name],
            col.logical_type,
            col.name,
            top_k=top_k,
            categorical_threshold=categorical_threshold,
            histogram_bins=histogram_bins,
        )
        for col in dataset.schema.columns
    )
    return Profile(schema=dataset.schema, row_count=int(len(frame)), columns=columns)


def _profile_column(
    series: pd.Series,
    logical_type: LogicalType,
    name: str,
    *,
    top_k: int,
    categorical_threshold: int,
    histogram_bins: int,
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
    counts = series.value_counts()
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
