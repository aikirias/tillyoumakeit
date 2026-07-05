"""Referentially-consistent subsetting (AD-26, PDE-16).

A subset is anchored at a **root** table: keep a deterministic fraction of its rows, then keep every
other row that is referentially connected to them, so the result is a smaller but still valid DB.

Two closures, run to a fixpoint:

- **Downward** — a descendant row (a child, grandchild, … reachable by following foreign keys *from*
  the root) is kept when a foreign key of it points at an already-kept row. This grows the kept set
  down the root's subtree.
- **Upward** — for every kept row, the parent rows it references are kept too (so its foreign keys
  are satisfied), **without** re-expanding those parents' other children. This keeps the dimensions
  a kept fact row needs.

Keys are **not renumbered** — a surviving row keeps its position-derived key (AD-16), so a subset
still joins to a full dataset generated from the same Spec. Single-column keys/FKs; a cyclic
inter-table FK graph fails closed. Composite keys and out-of-core streaming are deferred.
"""

from __future__ import annotations

from collections import defaultdict

from tymi.config.spec import Spec, spec_profiles
from tymi.core.errors import GenerationError
from tymi.core.rng import make_rng
from tymi.domain.artifacts import Dataset, GatedDataset
from tymi.privacy.classifier import classify_sensitive_columns
from tymi.synth.leakage import scan_and_gate
from tymi.synth.whole_db import _structural_columns


def subset_from_spec(
    spec: Spec, *, root: str, fraction: float
) -> dict[str, GatedDataset]:
    """Generate the whole DB from ``spec``, then return a referentially-consistent subset (AD-26).

    Keeps ``fraction`` of ``root`` (deterministic per the Spec's seed) and everything referentially
    connected to it; each subset table is re-sealed as a ``GatedDataset`` (row selection cannot
    introduce a real value, so the seal scan is a no-op).
    """
    from tymi.synth.whole_db import generate_from_spec

    gated = generate_from_spec(spec)
    datasets = {name: Dataset(frame=gd.frame, schema=gd.schema) for name, gd in gated.items()}
    subset = subset_datasets(datasets, root=root, fraction=fraction, seed=spec.seed)
    profiles = spec_profiles(spec)
    result: dict[str, GatedDataset] = {}
    for name, ds in subset.items():
        shared = tuple(spec.tables[name].shared_keys)
        result[name] = scan_and_gate(
            ds,
            profiles[name].leakage_guard,
            structural_columns=_structural_columns(ds.schema, shared),
            classify=classify_sensitive_columns,
        )
    return result


def subset_datasets(
    datasets: dict[str, Dataset], *, root: str, fraction: float, seed: int
) -> dict[str, Dataset]:
    """Filter ``datasets`` to a referentially-consistent subset anchored at ``root`` (AD-26).

    ``fraction`` (0, 1] of the root's rows are kept deterministically; keys are preserved. Inputs
    are not mutated. Fails closed on an unknown root, a bad fraction, a composite-key table, or a
    cyclic inter-table FK graph.
    """
    if root not in datasets:
        raise GenerationError(f"subset root {root!r} is not among the tables.")
    if not 0.0 < fraction <= 1.0:
        raise GenerationError(f"subset fraction must be in (0, 1], got {fraction}.")
    _require_single_column_keys(datasets)
    _require_acyclic(datasets)

    kept = _kept_keys(datasets, root=root, fraction=fraction, seed=seed)
    result: dict[str, Dataset] = {}
    for name, ds in datasets.items():
        (pk,) = ds.schema.primary_key
        mask = ds.frame[pk].isin(kept.get(name, set()))
        result[name] = Dataset(frame=ds.frame[mask].reset_index(drop=True), schema=ds.schema)
    return result


def _kept_keys(
    datasets: dict[str, Dataset], *, root: str, fraction: float, seed: int
) -> dict[str, set]:
    """The set of kept primary-key values per table (downward + upward closure to a fixpoint)."""
    (root_pk,) = datasets[root].schema.primary_key
    root_frame = datasets[root].frame
    n = len(root_frame)
    n_keep = max(1, round(n * fraction)) if n else 0
    root_pks = root_frame[root_pk].to_numpy()
    chosen = make_rng(seed).permutation(root_pks)[:n_keep]  # deterministic root sample
    kept: dict[str, set] = {root: set(chosen.tolist())}

    # The root's subtree = tables reachable from it by reverse-FK (its descendants). Downward only
    # expands within the subtree, so a dimension a kept row references (kept by the upward closure)
    # never re-expands its own other children — which would cascade to the whole DB.
    descendants = _descendants(datasets, root)
    subtree = descendants | {root}

    changed = True
    while changed:
        changed = False
        # Downward: keep a descendant row when a foreign key of it into the subtree is kept.
        for name in descendants:
            ds = datasets[name]
            (pk,) = ds.schema.primary_key
            new_rows: set = set()
            for fk in ds.schema.foreign_keys:
                parent = fk.referred_table
                if parent in subtree and parent in kept:
                    (child_col,) = fk.columns
                    mask = ds.frame[child_col].isin(kept[parent])
                    new_rows.update(ds.frame.loc[mask, pk].tolist())
            if not new_rows.issubset(kept.get(name, set())):
                kept[name] = kept.get(name, set()) | new_rows
                changed = True
        # Upward: keep every parent row a kept row references (satisfy all FKs, no re-expansion).
        for name, ds in datasets.items():
            if name not in kept:
                continue
            (pk,) = ds.schema.primary_key
            kept_rows = ds.frame[ds.frame[pk].isin(kept[name])]
            for fk in ds.schema.foreign_keys:
                (child_col,) = fk.columns
                referenced = set(kept_rows[child_col].dropna().tolist())
                if referenced and not referenced.issubset(kept.get(fk.referred_table, set())):
                    kept[fk.referred_table] = kept.get(fk.referred_table, set()) | referenced
                    changed = True
    return kept


def _descendants(datasets: dict[str, Dataset], root: str) -> set[str]:
    """Tables reachable from ``root`` by reverse foreign keys (its transitive children)."""
    referencers: dict[str, set[str]] = defaultdict(set)
    for name, ds in datasets.items():
        for fk in ds.schema.foreign_keys:
            if fk.referred_table != name:
                referencers[fk.referred_table].add(name)
    descendants: set[str] = set()
    frontier = {root}
    while frontier:
        nxt: set[str] = set()
        for parent in frontier:
            for child in referencers.get(parent, ()):
                if child != root and child not in descendants:
                    descendants.add(child)
                    nxt.add(child)
        frontier = nxt
    return descendants


def _require_single_column_keys(datasets: dict[str, Dataset]) -> None:
    for name, ds in datasets.items():
        if len(ds.schema.primary_key) != 1:
            raise GenerationError(
                f"table {name!r} must have exactly one primary-key column to be subset (it has "
                f"{len(ds.schema.primary_key)}); composite/no-PK tables are a Phase-3 limit."
            )
        for fk in ds.schema.foreign_keys:
            if len(fk.columns) != 1:
                raise GenerationError(
                    f"table {name!r} has a composite foreign key; subsetting supports "
                    "single-column foreign keys only (Phase-3 limit)."
                )


def _require_acyclic(datasets: dict[str, Dataset]) -> None:
    """Fail closed on a cyclic inter-table FK graph (self-references are allowed)."""
    deps = {
        name: {
            fk.referred_table
            for fk in ds.schema.foreign_keys
            if fk.referred_table != name and fk.referred_table in datasets
        }
        for name, ds in datasets.items()
    }
    remaining = {t: set(d) for t, d in deps.items()}
    while remaining:
        ready = [t for t, d in remaining.items() if not d]
        if not ready:
            raise GenerationError(
                f"cyclic foreign-key graph among {sorted(remaining)}; subsetting fails closed."
            )
        for t in ready:
            del remaining[t]
        for d in remaining.values():
            d.difference_update(ready)
