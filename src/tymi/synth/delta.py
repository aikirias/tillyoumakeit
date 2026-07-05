"""Incremental / delta refresh (AD-27, PDE-17).

Refreshing a large DB after a small Spec edit should be cheap: regenerate only the tables whose
inputs actually changed, and reuse the rest. Because keys are **position-derived** (AD-16), a
table's generated output is a pure function of its own inputs and its parents' *key-affecting*
inputs — so a precise per-table diff tells us exactly what is byte-identical to the previous run.

A table is **dirty** iff:

- it is **new** (absent from the previous Spec), or a global input changed (``seed`` /
  ``chunk_rows`` — those dirty everything); or
- its own pinned Profile, row count, shared-key / reserved-block decls, fixtures, or
  cross-correlations changed (a direct change); or
- a **direct parent** had a *key-affecting* change — its row count, shared keys, or reserved block —
  because those change the parent's key **values or range**, hence this table's foreign-key values.

A parent's *profile-only* change does **not** dirty its children: the parent's keys are unchanged,
so the children's FK values are unchanged. Key-affecting changes propagate exactly one hop (a
table dirtied only by a parent keeps its own keys, so its own children stay clean). A clean table is
**reused** — byte-identical to the previous run — so the caller reloads only the regenerated tables,
and referential integrity holds because the regenerated tables' position-derived keys still line up
with the reused tables' foreign keys.
"""

from __future__ import annotations

from dataclasses import dataclass

from tymi.config.consistency import consistency_fingerprint
from tymi.config.spec import Spec, spec_profiles
from tymi.domain.artifacts import GatedDataset
from tymi.synth.whole_db import generate_from_spec


@dataclass(frozen=True)
class DeltaResult:
    """The outcome of a delta refresh (AD-27)."""

    regenerated: dict[str, GatedDataset]
    reused: tuple[str, ...]
    dropped: tuple[str, ...]
    fingerprint: str

    def render(self) -> str:
        return (
            f"Delta refresh: {len(self.regenerated)} regenerated "
            f"{sorted(self.regenerated)}, {len(self.reused)} reused, "
            f"{len(self.dropped)} dropped {list(self.dropped)}.\n"
            f"Consistency-unit fingerprint: {self.fingerprint}"
        )


def delta_refresh(previous: Spec, new: Spec) -> DeltaResult:
    """Regenerate only the tables of ``new`` whose inputs changed vs ``previous`` (AD-27).

    Returns the regenerated (dirty) tables as ``GatedDataset``\\s, the names of the reused (clean,
    byte-identical) and dropped tables, and the new consistency-unit fingerprint. A clean table is
    guaranteed byte-identical to the previous run, so the caller can safely leave it in place.
    """
    dirty = _dirty_tables(previous, new)
    gated = generate_from_spec(new)
    regenerated = {name: gd for name, gd in gated.items() if name in dirty}
    reused = tuple(sorted(name for name in new.tables if name not in dirty))
    dropped = tuple(sorted(set(previous.tables) - set(new.tables)))
    return DeltaResult(regenerated, reused, dropped, consistency_fingerprint(new))


def _dirty_tables(previous: Spec, new: Spec) -> set[str]:
    if previous.seed != new.seed or previous.chunk_rows != new.chunk_rows:
        return set(new.tables)  # a global input changed → everything is dirty

    dirty = {
        name
        for name, ts in new.tables.items()
        if name not in previous.tables or _table_changed(previous.tables[name], ts)
    }
    key_affecting = {
        name
        for name in new.tables
        if _key_affecting(previous.tables.get(name), new.tables[name])
    }
    # Propagate one hop along FK edges: a table whose direct parent had a key-affecting change is
    # dirty (its FK values move with the parent's key values/range).
    profiles = spec_profiles(new)
    for name in new.tables:
        for fk in profiles[name].schema.foreign_keys:
            if fk.referred_table in key_affecting:
                dirty.add(name)
    # Propagate along cross-correlation edges to a fixpoint: a correlated child's data column is
    # reordered against its parent's DATA (AD-25), so if the parent is dirty (its data may have
    # changed), the child is dirty too — even for a parent profile-only change.
    changed = True
    while changed:
        changed = False
        for name, ts in new.tables.items():
            if name in dirty:
                continue
            if any(cc.parent_table in dirty for cc in ts.cross_correlations):
                dirty.add(name)
                changed = True
    return dirty


def _table_changed(previous_ts, new_ts) -> bool:
    """True if any direct input changed (profile, rows, keys, fixtures, correlations)."""
    return previous_ts.model_dump() != new_ts.model_dump()


def _key_affecting(previous_ts, new_ts) -> bool:
    """A change that moves this table's key VALUES or RANGE — so its children's FK values change."""
    if previous_ts is None:
        return True  # a new table's keys are new
    return (
        previous_ts.rows != new_ts.rows
        or previous_ts.shared_keys != new_ts.shared_keys
        or previous_ts.reserved_key_block != new_ts.reserved_key_block
    )
