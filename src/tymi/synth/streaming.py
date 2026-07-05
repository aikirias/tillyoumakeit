"""Out-of-core, chunked whole-DB generation (AD-22/AD-23/AD-24).

A table is generated one bounded-memory **block** at a time instead of all at once, so an
arbitrarily large table never has to fit in RAM. Block ``k`` (global positions
``[k·chunk_rows, …)``) reuses the shipped :func:`~tymi.synth.generator.generate_faithful` seeded by
:func:`~tymi.synth.substreams.table_substream` with the block index (AD-22). Keys are assigned by
**global position** — a surrogate PK is ``offset + arange`` and a shared key is
``reserved + col_offset + position`` (AD-16) — so a key is a pure function of position, independent
of the chunk boundaries, and a child block resolves a foreign key from a parent *position* without
ever loading the parent (AD-23) — a composite or natural-key FK target is not position-addressable
and fails closed (the in-memory path handles those).

The concatenation of a table's blocks is byte-identical for a given ``(seed, table, chunk_rows)``.
This module produces plain ``Dataset`` blocks; sealing each into a ``GatedDataset`` and streaming it
to a destination is P2.3.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

import numpy as np

from tymi.core.errors import GenerationError, KeyspaceError
from tymi.domain.artifacts import Dataset, LogicalType, Profile
from tymi.synth.generator import generate_faithful
from tymi.synth.substreams import table_substream


@dataclass(frozen=True)
class ParentKeyRule:
    """How a parent's position maps to its (position-addressable) key (AD-23).

    ``key(position) = base + position``: ``base`` is ``0`` for a surrogate integer PK and
    ``reserved + col_offset`` for a shared key. A child resolves a foreign key by drawing a parent
    **position** in ``[0, total_rows)`` and mapping it here — the parent is never materialised.
    """

    total_rows: int
    base: int = 0

    def keys(self, positions: np.ndarray) -> np.ndarray:
        return self.base + positions


def generate_table_chunks(
    profile: Profile,
    *,
    total_rows: int,
    seed: int,
    table: str,
    chunk_rows: int,
    shared_keys: tuple[str, ...] = (),
    reserved: int = 0,
    fk_rules: dict[tuple[str, str], ParentKeyRule] | None = None,
) -> Iterator[Dataset]:
    """Yield ``profile``'s table as bounded-memory blocks of ``chunk_rows`` (AD-22/AD-23).

    Each block is a faithful sample drawn from the block substream, with a surrogate integer primary
    key and declared shared keys assigned by **global position**. When ``fk_rules`` is provided
    (the whole-DB streaming mode, keyed by ``(referred_table, referred_column)``), single-column
    foreign keys are resolved by drawing parent positions and mapping them through the rule — the
    parent is never loaded — and an FK with no rule or a composite FK **fails closed** (a natural
    or composite parent key is out of Phase-2 scope). With ``fk_rules=None`` (single-table mode)
    FKs are left untouched. Peak memory is ``O(chunk_rows)``.
    """
    if chunk_rows <= 0:
        raise ValueError(f"chunk_rows must be positive, got {chunk_rows}")
    _validate_shared_keys(profile, shared_keys, reserved, table)
    schema = profile.schema
    surrogate_pks = _surrogate_pk_columns(profile)
    offset = 0
    chunk_index = 0
    while offset < total_rows:
        block_len = min(chunk_rows, total_rows - offset)
        rng = table_substream(seed, table, chunk_index)
        frame = generate_faithful(profile, rows=block_len, rng=rng).frame.copy()
        positions = offset + np.arange(block_len, dtype=np.int64)
        _assign_position_keys(frame, surrogate_pks, shared_keys, positions, total_rows, reserved)
        if fk_rules is not None:
            _resolve_foreign_keys(frame, schema, fk_rules, rng, table)
        yield Dataset(frame=frame, schema=schema)
        offset += block_len
        chunk_index += 1


def _resolve_foreign_keys(
    frame, schema, rules: dict[tuple[str, str], ParentKeyRule], rng, table: str
) -> None:
    """Point each FK at a real parent key by drawing a parent position (AD-23), fail-closed.

    Every foreign key must be **single-column** and have a position-addressable rule keyed by
    ``(referred_table, referred_column)``; a composite FK or a missing rule (a natural-key parent)
    fails closed with :class:`GenerationError` — the in-memory path handles those. A rule with
    ``total_rows == 0`` (an empty parent) leaves the FK as generated (Phase-1 dangling parity)
    rather than divide by zero.
    """
    for fk in schema.foreign_keys:
        if len(fk.columns) != 1 or len(fk.referred_columns) != 1:
            raise GenerationError(
                f"composite foreign key {fk.columns} in {table!r} → {fk.referred_table} is not "
                "position-addressable for streaming (Phase-2 limit); use the in-memory path."
            )
        (child_col,) = fk.columns
        (parent_col,) = fk.referred_columns
        rule = rules.get((fk.referred_table, parent_col))
        if rule is None:
            raise GenerationError(
                f"foreign key {child_col!r} in {table!r} → {fk.referred_table}.{parent_col} has no "
                "position-addressable rule (a natural-key parent is out of Phase-2 scope)."
            )
        if rule.total_rows <= 0 or child_col not in frame.columns:
            continue
        draws = rng.integers(0, rule.total_rows, size=len(frame)).astype(np.int64)
        frame[child_col] = _as_dtype(rule.keys(draws), frame[child_col])


def _surrogate_pk_columns(profile: Profile) -> tuple[str, ...]:
    """The single-column surrogate integer PK to assign by global position, or ``()``.

    Only a **single-column** integer PK that is **not** itself a foreign key is a position
    surrogate; a composite PK or an integer natural/FK key is left as generated (position keys for
    those are out of P2.1 scope).
    """
    pk = profile.schema.primary_key
    if len(pk) != 1:
        return ()
    (col,) = pk
    integer = {c.name for c in profile.schema.columns if c.logical_type == LogicalType.INTEGER}
    fk_columns = {c for fk in profile.schema.foreign_keys for c in fk.columns}
    return (col,) if col in integer and col not in fk_columns else ()


def _validate_shared_keys(
    profile: Profile, shared_keys: tuple[str, ...], reserved: int, table: str
) -> None:
    """Fail closed (mirrors in-memory ``apply_shared_keys``) on a mis-declared shared key."""
    if reserved < 0:
        raise KeyspaceError(f"reserved key block for {table!r} must be >= 0, got {reserved}")
    column_names = {c.name for c in profile.schema.columns}
    fk_columns = {c for fk in profile.schema.foreign_keys for c in fk.columns}
    for col in shared_keys:
        if col not in column_names:
            raise KeyspaceError(f"shared column {col!r} is not in table {table!r}")
        if col in fk_columns:
            raise KeyspaceError(
                f"shared column {col!r} in {table!r} is a foreign key; it must follow its "
                "parent's shared key, not be rewritten independently."
            )


def _assign_position_keys(
    frame,
    surrogate_pks: tuple[str, ...],
    shared_keys: tuple[str, ...],
    positions: np.ndarray,
    total_rows: int,
    reserved: int,
) -> None:
    """Overwrite surrogate PKs with the global position; shared keys with ``reserved+offset+pos``.

    Shared keys win over the surrogate-PK assignment for a column that is both (matching the
    in-memory order in :func:`tymi.synth.keys.apply_shared_keys`); multiple shared columns are
    packed into disjoint sub-ranges by column index, exactly as AD-16 does in memory.
    """
    for pk in surrogate_pks:
        if pk in frame.columns:
            frame[pk] = _as_dtype(positions, frame[pk])
    for col_index, col in enumerate(shared_keys):
        if col in frame.columns:
            keys = reserved + col_index * total_rows + positions
            frame[col] = _as_dtype(keys, frame[col])


def _as_dtype(values: np.ndarray, column):
    import pandas as pd

    return pd.Series(values, index=column.index).astype(column.dtype)
