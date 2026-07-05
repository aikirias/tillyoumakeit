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

from tymi.config.spec import Spec, spec_profiles
from tymi.core.errors import GenerationError, KeyspaceError
from tymi.domain.artifacts import Dataset, GatedDataset, LogicalType, Profile
from tymi.privacy.classifier import classify_sensitive_columns
from tymi.synth.generator import generate_faithful
from tymi.synth.leakage import scan_and_gate
from tymi.synth.relational import _topological_order
from tymi.synth.substreams import table_substream
from tymi.synth.whole_db import _require_fk_complete, _structural_columns


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
    # Always yield at least one block — an EMPTY one for a 0-row table — so the destination table
    # is always materialised/truncated on the streaming write (otherwise a table that dropped to 0
    # rows would leave stale rows behind, breaking idempotency, AD-24).
    while offset < total_rows or chunk_index == 0:
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


# --- whole-DB streaming orchestration (AD-22/23/24) -------------------------


@dataclass(frozen=True)
class StreamChunk:
    """One sealed block of a streamed table: table name, 0-based chunk index, GatedDataset."""

    table: str
    chunk_index: int
    gated: GatedDataset


def stream_from_spec(spec: Spec) -> Iterator[StreamChunk]:
    """Stream the whole DB as sealed, bounded-memory chunks in FK-topological order (AD-22/23/24).

    Each table is generated one ``spec.chunk_rows`` block at a time; foreign keys are resolved by
    parent position (the parent is never loaded), and each block is sealed into a ``GatedDataset``
    (AD-21) before it is yielded. Peak memory is one block regardless of a table's size.

    Fixtures are **not** overlaid on the streaming path yet: a table that pins fixtures fails closed
    with a clear message (fixtures are small — use the in-memory ``generate_from_spec`` for a DB
    that needs them). This is a documented Phase-2 limit.
    """
    profiles = spec_profiles(spec)
    _require_fk_complete(profiles)
    for table in _topological_order(profiles):
        ts = spec.tables[table]
        if ts.fixtures:
            raise GenerationError(
                f"table {table!r} pins fixtures, which the streaming path does not overlay yet; "
                "use the in-memory generate_from_spec for a DB with fixtures (Phase-2 limit)."
            )
        profile = profiles[table]
        shared = tuple(ts.shared_keys)
        rules = _fk_rules_for(spec, profiles, table)
        structural = _structural_columns(profile.schema, shared)
        for index, block in enumerate(
            generate_table_chunks(
                profile,
                total_rows=ts.rows,
                seed=spec.seed,
                table=table,
                chunk_rows=spec.chunk_rows,
                shared_keys=shared,
                reserved=ts.reserved_key_block,
                fk_rules=rules,
            )
        ):
            sealed = scan_and_gate(
                block,
                profile.leakage_guard,
                structural_columns=structural,
                classify=classify_sensitive_columns,
            )
            yield StreamChunk(table=table, chunk_index=index, gated=sealed)


def _fk_rules_for(
    spec: Spec, profiles: dict[str, Profile], table: str
) -> dict[tuple[str, str], ParentKeyRule]:
    """Build position-addressable FK rules for ``table`` from the Spec (unresolved target → none).

    A referred column that is a parent **shared key** maps to ``reserved + col_index·rows``; a
    parent **single-column integer surrogate PK** maps to ``base 0``. A natural-key target gets no
    rule, so :func:`generate_table_chunks` fails closed on it (AD-23).
    """
    rules: dict[tuple[str, str], ParentKeyRule] = {}
    for fk in profiles[table].schema.foreign_keys:
        parent = fk.referred_table
        parent_ts = spec.tables.get(parent)
        if parent_ts is None:
            continue  # out-of-spec parent → generate_table_chunks fails closed on the missing rule
        parent_total = parent_ts.rows
        parent_shared = list(parent_ts.shared_keys)
        for parent_col in fk.referred_columns:
            if parent_col in parent_shared:
                col_index = parent_shared.index(parent_col)
                base = parent_ts.reserved_key_block + col_index * parent_total
                rules[(parent, parent_col)] = ParentKeyRule(parent_total, base)
            elif parent_col in _surrogate_pk_columns(profiles[parent]):
                rules[(parent, parent_col)] = ParentKeyRule(parent_total, 0)
    return rules
