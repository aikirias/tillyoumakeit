"""Cross-table single-hop correlation by rank-correlation induction (AD-25, PDE-6).

By default a child column is generated independently of the parent row it references. When the
source has a real dependency (order amount ↔ customer tier), a declared cross-correlation
``(child.column ↔ parent.column, ρ)`` restores it **after** ``generate_related`` has set the FK
edges — by a Gaussian-copula **reorder**: the child column is permuted so its Spearman correlation
with the referenced parent value is ≈ ρ, while the child column's **marginal is preserved** (a
reorder never invents or drops a value). Deterministic (injected rng, AD-4).

Scope (single-hop, in-memory): a direct child→parent FK only. A self / cyclic / non-existent parent
FK, or correlating a key/FK column, **fails closed**. Reordering one column can perturb its
*intra-table* correlations with its siblings — documented single-column limit; a joint multivariate
induction is a follow-up. Combining this with out-of-core streaming is out of scope (a child block
would need its parent's referenced values, which are not position-addressable).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.special import ndtri
from scipy.stats import rankdata

from tymi.core.errors import GenerationError
from tymi.domain.artifacts import Dataset, LogicalType
from tymi.synth.substreams import table_substream

_NUMERIC = {LogicalType.INTEGER, LogicalType.FLOAT}


def induce_rank_correlation(
    target: np.ndarray, reference: np.ndarray, rho: float, rng: np.random.Generator
) -> np.ndarray:
    """Reorder ``target`` so its Spearman correlation with ``reference`` is ≈ ``rho``.

    A Gaussian-copula reorder: rank ``reference`` into normal scores, mix with independent noise at
    strength ``rho``, and assign the sorted ``target`` values by the resulting latent order. The
    result is a **permutation** of ``target`` (its marginal is preserved). ``rho`` is clamped to
    ``[-1, 1]``.
    """
    n = len(target)
    if n < 2:
        return np.asarray(target)
    rho = float(np.clip(rho, -1.0, 1.0))
    z_reference = ndtri(rankdata(reference) / (n + 1))
    latent = rho * z_reference + np.sqrt(1.0 - rho * rho) * rng.standard_normal(n)
    latent_rank = np.argsort(np.argsort(latent))  # 0-based rank of each row's latent value
    return np.sort(target)[latent_rank]


def apply_cross_correlations(
    datasets: dict[str, Dataset], spec, *, seed: int
) -> dict[str, Dataset]:
    """Apply every declared cross-correlation in the Spec to a copy of ``datasets`` (AD-25).

    ``spec`` is a :class:`~tymi.config.spec.Spec`. Each table's correlations draw from their **own
    independent** substream ``(seed, "<table>::xcorr")``, so a change to one table's correlation
    never perturbs another's (this keeps the incremental-refresh diff, AD-27, sound). Inputs are not
    mutated. Fails closed via :class:`~tymi.core.errors.GenerationError` on a mis-declared
    correlation.
    """
    if not any(ts.cross_correlations for ts in spec.tables.values()):
        return datasets
    result = {
        t: Dataset(frame=ds.frame.copy(deep=True), schema=ds.schema)
        for t, ds in datasets.items()
    }
    for table in sorted(spec.tables):
        correlations = spec.tables[table].cross_correlations
        if not correlations:
            continue
        rng = table_substream(seed, f"{table}::xcorr")
        for cc in correlations:
            _apply_one(result, table, cc, rng)
    return result


def _apply_one(result: dict[str, Dataset], table: str, cc, rng: np.random.Generator) -> None:
    child = result[table]
    parent = result.get(cc.parent_table)
    if parent is None:
        raise GenerationError(
            f"cross-correlation on {table}.{cc.column} references parent {cc.parent_table!r}, "
            "which is not in the spec."
        )
    if cc.parent_table == table:
        raise GenerationError(
            f"cross-correlation on {table}.{cc.column} is self-referential; single-hop only."
        )
    fk = _direct_fk(child, cc.parent_table)
    if fk is None:
        raise GenerationError(
            f"cross-correlation on {table}.{cc.column} needs a direct foreign key to "
            f"{cc.parent_table!r}, but none exists."
        )
    key_columns = _key_columns(child)
    if cc.column not in child.frame.columns or cc.column in key_columns:
        raise GenerationError(
            f"cross-correlation column {cc.column!r} must be a non-key data column of {table!r}."
        )
    if cc.parent_column not in parent.frame.columns:
        raise GenerationError(
            f"parent column {cc.parent_column!r} is not in {cc.parent_table!r}."
        )
    if _logical_type(child, cc.column) not in _NUMERIC:
        raise GenerationError(f"cross-correlation column {cc.column!r} must be numeric.")
    if _logical_type(parent, cc.parent_column) not in _NUMERIC:
        raise GenerationError(f"parent column {cc.parent_column!r} must be numeric.")
    child_col, parent_key = fk.columns[0], fk.referred_columns[0]
    parent_lookup = parent.frame.set_index(parent_key)[cc.parent_column]
    parent_values = _as_float(parent_lookup.reindex(child.frame[child_col]))
    original = child.frame[cc.column]
    reordered = induce_rank_correlation(_as_float(original), parent_values, cc.rho, rng)
    # Assign back via a pandas Series so a nullable Int64 / boolean data column round-trips (a numpy
    # astype cannot interpret a pandas ExtensionDtype).
    child.frame[cc.column] = pd.Series(reordered, index=original.index).astype(original.dtype)


def _as_float(series) -> np.ndarray:
    """A numeric column as a plain ``float64`` array (nullable NA → NaN), for ranking/sorting."""
    numeric = pd.to_numeric(pd.Series(series), errors="coerce")
    return numeric.to_numpy(dtype="float64", na_value=np.nan)


def _logical_type(dataset: Dataset, column: str):
    return next((c.logical_type for c in dataset.schema.columns if c.name == column), None)


def _direct_fk(child: Dataset, parent_table: str):
    for fk in child.schema.foreign_keys:
        if fk.referred_table == parent_table and len(fk.columns) == 1:
            return fk
    return None


def _key_columns(dataset: Dataset) -> set[str]:
    schema = dataset.schema
    columns = set(schema.primary_key)
    for fk in schema.foreign_keys:
        columns.update(fk.columns)
    return columns
