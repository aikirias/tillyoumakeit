"""Cross-column correlation detection (Story 1.7).

From a profiled Dataset, detect pairwise associations so faithful generation
(Epic 2) can later preserve them:

- **numeric** columns → Spearman rank correlation (robust to non-linearity and
  outliers, and exactly the correlation consumed by the in-house Gaussian
  copula in Epic 2, AD-9 — no re-estimation needed downstream).
- **categorical** columns → first-order dependencies via Cramér's V, computed
  from a pairwise-complete contingency table with an in-house chi² (no scipy
  dependency); symmetric and in ``[0, 1]``.

AD-6: only aggregate association coefficients + column names are stored, never
raw row values. Undefined coefficients (constant column, zero overlap) are
``None`` so the artifact serializes to valid JSON (``null``, never bare ``NaN``).
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd

from tymi.domain.artifacts import ColumnProfile, CorrelationMatrix, Correlations

#: Coefficients are rounded to this many decimals so the serialized Profile is
#: stable across platforms (float noise would otherwise churn the artifact).
_ROUND = 6


def detect_correlations(
    frame: pd.DataFrame,
    column_profiles: Sequence[ColumnProfile],
    *,
    max_categorical_cardinality: int,
) -> Correlations | None:
    """Detect numeric + categorical correlations from already-profiled columns.

    Which columns are numeric vs categorical is taken from the per-column
    ``ColumnProfile``s (numeric stats present → numeric; category labels present
    → categorical) so detection stays consistent with per-column profiling.
    """
    numeric_cols = [
        p.name for p in column_profiles if p.numeric is not None and p.distinct_count >= 2
    ]
    categorical_cols = [
        p.name
        for p in column_profiles
        if p.categories is not None and 2 <= p.distinct_count <= max_categorical_cardinality
    ]
    numeric = _numeric_correlation(frame, numeric_cols)
    categorical = _categorical_associations(frame, categorical_cols)
    if numeric is None and categorical is None:
        return None
    return Correlations(numeric=numeric, categorical=categorical)


def _numeric_correlation(frame: pd.DataFrame, cols: list[str]) -> CorrelationMatrix | None:
    numeric = frame[cols].apply(pd.to_numeric, errors="coerce")
    # Exclude columns that are constant *after* coercion (Spearman is undefined for
    # them and would only contribute all-``None`` cells). ``distinct_count`` was
    # computed on raw values, so e.g. {"1.0","1.00"} could slip through upstream.
    kept = [c for c in cols if numeric[c].nunique(dropna=True) >= 2]
    if len(kept) < 2:
        return None
    corr = numeric[kept].corr(method="spearman", min_periods=1)
    matrix = tuple(
        tuple(_clean(corr.iat[i, j]) for j in range(len(kept))) for i in range(len(kept))
    )
    return CorrelationMatrix(method="spearman", columns=tuple(kept), matrix=matrix)


def _categorical_associations(frame: pd.DataFrame, cols: list[str]) -> CorrelationMatrix | None:
    if len(cols) < 2:
        return None
    n = len(cols)
    matrix: list[list[float | None]] = [[None] * n for _ in range(n)]
    for i in range(n):
        matrix[i][i] = 1.0
        for j in range(i + 1, n):
            v = _cramers_v(frame[cols[i]], frame[cols[j]])
            matrix[i][j] = v
            matrix[j][i] = v
    return CorrelationMatrix(
        method="cramers_v",
        columns=tuple(cols),
        matrix=tuple(tuple(row) for row in matrix),
    )


def _cramers_v(a: pd.Series, b: pd.Series) -> float | None:
    """Cramér's V over rows where both columns are present (pairwise-complete)."""
    pair = pd.DataFrame({"a": a.reset_index(drop=True), "b": b.reset_index(drop=True)}).dropna()
    if pair.empty:
        return None
    table = pd.crosstab(pair["a"], pair["b"]).to_numpy(dtype=float)
    total = table.sum()
    r, k = table.shape
    if total == 0 or min(r, k) < 2:
        return None
    row_sums = table.sum(axis=1, keepdims=True)
    col_sums = table.sum(axis=0, keepdims=True)
    expected = row_sums @ col_sums / total  # every marginal > 0 → no divide-by-zero
    chi2 = float(((table - expected) ** 2 / expected).sum())
    v = np.sqrt(chi2 / (total * (min(r, k) - 1)))
    return round(float(min(v, 1.0)), _ROUND)


def _clean(value: float) -> float | None:
    v = float(value)
    if not np.isfinite(v):
        return None
    return round(v, _ROUND)
