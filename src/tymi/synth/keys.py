"""Position-derived shared keys + reserved fixture keyspace (AD-16, PDE-12, closes OQ-5).

A column declared ``shared`` in the Spec is a cross-team join key: two teams that pin the same
per-table row counts must get **identical** values for it, independent of the source data **and**
of the seed. We emit them position-derived::

    key(table, position) = reserved_key_block + position

so the values depend only on the table (which column is keyed) and the row position — never on the
source or the RNG. Given identical pinned row counts, two teams' shared keys line up exactly, so
their datasets join consistently.

**OQ-5 resolution — the reserved-keyspace convention.** The reserved fixture block is the
contiguous integer range ``[0, reserved_key_block)`` per table. Pinned fixtures (AD-17) draw keys
from **inside** it; generated shared keys are emitted **at/above** it — ``[reserved, reserved + n)``
— so the two are disjoint by construction. We still validate the invariant and **fail closed**
(:class:`KeyspaceError`) on any violation: a fixture key outside the reserved block, a negative
block, or a shared column that is itself a foreign key (which cannot be independently rewritten
without orphaning its parent).

When a shared column is a primary/unique key that foreign keys reference, rewriting it in place
would orphan those FKs; every referencing FK is remapped by the same ``old -> new`` key mapping so
referential integrity is preserved across the whole DB. Under Phase-3 subsetting, keys must
re-attach to surviving rows — deferred.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from tymi.core.errors import KeyspaceError
from tymi.domain.artifacts import Dataset


def position_keys(reserved: int, n: int, offset: int = 0) -> np.ndarray:
    """The ``n`` position-derived shared keys for one column, in ``[reserved+offset, +n)``.

    ``offset`` packs a table's multiple shared columns into disjoint sub-ranges (each column of
    the same table shares the row count ``n``), so two independent shared columns never collapse
    to identical values while each stays source/seed-independent.
    """
    return reserved + offset + np.arange(n, dtype=np.int64)


def apply_shared_keys(
    datasets: dict[str, Dataset],
    *,
    shared_by_table: dict[str, list[str]],
    reserved_by_table: dict[str, int],
    fixture_keys_by_table: dict[str, dict[str, list]] | None = None,
) -> dict[str, Dataset]:
    """Overwrite declared shared columns with position-derived keys, remapping referencing FKs.

    ``shared_by_table`` maps a table to its declared shared columns; ``reserved_by_table`` to its
    reserved fixture-block size; ``fixture_keys_by_table`` (optional) to the fixture keys already
    pinned per shared column, which must lie inside the reserved block. Returns a new dict of
    Datasets (inputs are not mutated). Fails closed via :class:`KeyspaceError`.
    """
    fixture_keys_by_table = fixture_keys_by_table or {}
    result = {
        t: Dataset(frame=ds.frame.copy(deep=True), schema=ds.schema)
        for t, ds in datasets.items()
    }

    # Pass 1: rewrite shared columns to position-derived keys; record old->new maps for remapping.
    mappings: dict[str, dict[str, dict[object, int]]] = {}
    for table, shared_cols in shared_by_table.items():
        if not shared_cols:
            continue
        if table not in result:
            raise KeyspaceError(
                f"shared keys declared for table {table!r}, which was not generated"
            )
        ds = result[table]
        reserved = reserved_by_table.get(table, 0)
        if reserved < 0:
            raise KeyspaceError(f"reserved key block for {table!r} must be >= 0, got {reserved}")
        fk_columns = {c for fk in ds.schema.foreign_keys for c in fk.columns}
        composite_referred = _composite_referred_columns(datasets, table)
        table_fixture_keys = fixture_keys_by_table.get(table, {})
        n = len(ds.frame)
        offset = 0
        for col in shared_cols:
            if col not in ds.frame.columns:
                raise KeyspaceError(f"shared column {col!r} is not in table {table!r}")
            if col in fk_columns:
                raise KeyspaceError(
                    f"shared column {col!r} in {table!r} is a foreign key; a foreign key cannot "
                    "be a shared key (it must follow its parent's shared key, not be rewritten "
                    "independently)."
                )
            if col in composite_referred:
                raise KeyspaceError(
                    f"shared column {col!r} in {table!r} is part of a composite foreign-key "
                    "reference; composite shared keys are not supported in Phase 1."
                )
            original = ds.frame[col]
            if not original.is_unique:
                raise KeyspaceError(
                    f"shared column {col!r} in {table!r} has duplicate values; a shared key must "
                    "be unique so it can be a stable cross-team join key."
                )
            _validate_fixture_block(table_fixture_keys.get(col, ()), reserved, table, col)
            new_keys = position_keys(reserved, n, offset)
            old = original.to_numpy()
            # Preserve the column's declared dtype (e.g. nullable Int64), not raw numpy int64.
            ds.frame[col] = pd.Series(new_keys, index=ds.frame.index).astype(original.dtype)
            mappings.setdefault(table, {})[col] = {
                o: int(k) for o, k in zip(old.tolist(), new_keys.tolist(), strict=True)
            }
            offset += n

    # Pass 2: remap every FK that references a rewritten shared key (RI across the whole DB).
    for ds in result.values():
        for fk in ds.schema.foreign_keys:
            parent_maps = mappings.get(fk.referred_table)
            if not parent_maps:
                continue
            for child_col, parent_col in zip(fk.columns, fk.referred_columns, strict=True):
                mp = parent_maps.get(parent_col)
                if mp is None:
                    continue
                original = ds.frame[child_col]
                remapped = original.map(mp)
                # Every in-spec FK value pointed at a real (now-rewritten) parent key, so all
                # non-null values must remap; a gap means the FK was already dangling — fail closed.
                unmapped = remapped.isna() & original.notna()
                if unmapped.any():
                    raise KeyspaceError(
                        f"foreign key {child_col!r} references parent {fk.referred_table}."
                        f"{parent_col} values with no parent row; cannot remap shared keys."
                    )
                ds.frame[child_col] = remapped.astype(original.dtype)

    return result


def _composite_referred_columns(datasets: dict[str, Dataset], parent_table: str) -> set[str]:
    """Columns of ``parent_table`` referenced by a *composite* (multi-column) foreign key.

    A single shared column that is part of a composite key cannot be rewritten independently
    without breaking the tuple correspondence, so sharing it fails closed (Phase 1 scope).
    """
    referred: set[str] = set()
    for ds in datasets.values():
        for fk in ds.schema.foreign_keys:
            if fk.referred_table == parent_table and len(fk.referred_columns) > 1:
                referred.update(fk.referred_columns)
    return referred


def _validate_fixture_block(fixture_keys, reserved: int, table: str, col: str) -> None:
    """Every fixture key for ``col`` must lie strictly inside ``[0, reserved)`` (fail closed)."""
    for key in fixture_keys:
        if not (0 <= key < reserved):
            raise KeyspaceError(
                f"fixture key {key!r} for {table}.{col} is outside the reserved block "
                f"[0, {reserved}); fixtures and generated shared keys must stay disjoint."
            )


def shared_specs(spec) -> tuple[dict[str, list[str]], dict[str, int]]:
    """Extract ``(shared_by_table, reserved_by_table)`` from a Spec (keeps synth config-agnostic).

    ``spec`` is a :class:`~tymi.config.spec.Spec`; typed loosely so this module needs no import of
    the config layer.
    """
    shared_by_table = {name: list(ts.shared_keys) for name, ts in spec.tables.items()}
    reserved_by_table = {name: ts.reserved_key_block for name, ts in spec.tables.items()}
    return shared_by_table, reserved_by_table
