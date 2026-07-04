"""Canonical-Schema-driven normalization for export (Story 2.6, AR-10).

Exporters serialize from the canonical ``Schema``, not from whatever pandas dtype a
column happens to carry. ``normalize_for_export`` coerces each column to the pandas
representation implied by its ``LogicalType`` (nullable ``Int64`` for INTEGER, native
``datetime64`` for DATETIME, nullable ``boolean`` for BOOLEAN, …) and orders columns
by the Schema, so every exporter renders the *declared* type deterministically
regardless of how the generator backed it (e.g. a suppressed sensitive column that
came through as object-null still exports as its declared type).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from tymi.domain.artifacts import Dataset, LogicalType


def normalize_for_export(dataset: Dataset) -> pd.DataFrame:
    """Return a DataFrame with each column coerced to its ``LogicalType`` (AR-10)."""
    frame = dataset.frame
    data = {
        col.name: _coerce(frame[col.name], col.logical_type)
        for col in dataset.schema.columns
        if col.name in frame.columns
    }
    ordered = [c.name for c in dataset.schema.columns if c.name in frame.columns]
    return pd.DataFrame(data, columns=ordered, index=frame.index)


def _coerce(series: pd.Series, logical_type: LogicalType) -> pd.Series:
    if logical_type == LogicalType.INTEGER:
        # Honour the declared INTEGER type (AR-10): round-then-Int64 so a float-backed
        # integer (an int column that carried NULLs and loaded as float64) serializes
        # as an integer. NA-safe; non-finite (inf) is dropped to NA so it cannot crash
        # the cast or emit a non-portable literal.
        numeric = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan)
        return numeric.round().astype("Int64")
    if logical_type == LogicalType.FLOAT:
        # inf is not representable in JSON and non-portable in CSV → normalize to NA.
        return pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan).astype(
            "float64"
        )
    if logical_type == LogicalType.BOOLEAN:
        return series.astype("boolean")
    if logical_type == LogicalType.DATETIME:
        return pd.to_datetime(series, errors="coerce")
    # STRING / CATEGORICAL: object strings, nulls preserved as NA. ``map`` (not
    # ``where``) so an extension-dtype-backed column is actually stringified rather
    # than keeping its numeric dtype.
    return series.map(lambda v: v if pd.isna(v) else str(v)).astype(object)
