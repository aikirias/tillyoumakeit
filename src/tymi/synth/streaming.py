"""Out-of-core, chunked whole-DB generation (AD-22/AD-23/AD-24).

A table is generated one bounded-memory **block** at a time instead of all at once, so an
arbitrarily large table never has to fit in RAM. Block ``k`` (global positions
``[k·chunk_rows, …)``) reuses the shipped :func:`~tymi.synth.generator.generate_faithful` seeded by
:func:`~tymi.synth.substreams.table_substream` with the block index (AD-22). Keys are assigned by
**global position** — a surrogate PK is ``offset + arange`` and a shared key is
``reserved + col_offset + position`` (AD-16) — so a key is a pure function of position, independent
of the chunk boundaries, and a child block can resolve a foreign key from a parent *position*
without ever loading the parent (:mod:`tymi.synth.keys` position rules; AD-23 lands in P2.2).

The concatenation of a table's blocks is byte-identical for a given ``(seed, table, chunk_rows)``.
This module produces plain ``Dataset`` blocks; sealing each into a ``GatedDataset`` and streaming it
to a destination is P2.3.
"""

from __future__ import annotations

from collections.abc import Iterator

import numpy as np

from tymi.core.errors import KeyspaceError
from tymi.domain.artifacts import Dataset, LogicalType, Profile
from tymi.synth.generator import generate_faithful
from tymi.synth.substreams import table_substream


def generate_table_chunks(
    profile: Profile,
    *,
    total_rows: int,
    seed: int,
    table: str,
    chunk_rows: int,
    shared_keys: tuple[str, ...] = (),
    reserved: int = 0,
) -> Iterator[Dataset]:
    """Yield ``profile``'s table as bounded-memory blocks of ``chunk_rows`` (AD-22).

    Each block is a faithful sample drawn from the block substream, with a surrogate integer primary
    key and declared shared keys assigned by **global position**. Peak memory is ``O(chunk_rows)``.
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
        yield Dataset(frame=frame, schema=schema)
        offset += block_len
        chunk_index += 1


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
