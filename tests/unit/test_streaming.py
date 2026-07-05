"""PRD 1 Phase 2 · P2.1: chunk-aware substreams + chunked single-table generation (AD-22)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tymi.config.consistency import consistency_fingerprint
from tymi.config.spec import bootstrap_spec
from tymi.core.errors import KeyspaceError
from tymi.domain.artifacts import Column, Dataset, ForeignKey, LogicalType, Schema
from tymi.profiling.profiler import profile_dataset
from tymi.synth.streaming import generate_table_chunks
from tymi.synth.substreams import table_substream

_SCHEMA = Schema(
    columns=(
        Column("customer_id", LogicalType.INTEGER, primary_key=True),
        Column("score", LogicalType.FLOAT),
        Column("email", LogicalType.STRING),
    ),
    primary_key=("customer_id",),
)

_REAL_EMAILS = [f"real.person{i}@corp.example" for i in range(60)]


def _profile(n=60):
    rng = np.random.default_rng(0)
    frame = pd.DataFrame(
        {
            "customer_id": range(9000, 9000 + n),
            "score": rng.normal(0, 1, n),
            "email": _REAL_EMAILS[:n],
        }
    )
    return profile_dataset(
        Dataset(frame=frame, schema=_SCHEMA), sensitive_columns=["email"], salt="s"
    )


def _gen(*, total_rows, chunk_rows, seed=3, **kw):
    return list(
        generate_table_chunks(
            _profile(), total_rows=total_rows, seed=seed, table="customers",
            chunk_rows=chunk_rows, **kw,
        )
    )


def _concat(blocks):
    return pd.concat([b.frame for b in blocks], ignore_index=True)


# --- chunk-aware substream ---------------------------------------------------


def test_chunk_index_yields_independent_streams() -> None:
    a = table_substream(7, "customers", 0).integers(0, 1_000_000, size=10)
    b = table_substream(7, "customers", 1).integers(0, 1_000_000, size=10)
    assert not np.array_equal(a, b)


def test_chunk_none_is_the_phase1_stream_unchanged() -> None:
    whole = table_substream(7, "customers").integers(0, 1_000_000, size=10)
    also = table_substream(7, "customers", None).integers(0, 1_000_000, size=10)
    assert np.array_equal(whole, also)


# --- chunked generation (AD-22) ---------------------------------------------


def test_blocks_are_bounded_and_cover_all_rows() -> None:
    blocks = _gen(total_rows=250, chunk_rows=100)
    lengths = [len(b.frame) for b in blocks]
    assert lengths == [100, 100, 50]  # bounded by chunk_rows; last block is the remainder
    assert all(len(b.frame) <= 100 for b in blocks)  # peak memory is one block
    assert len(_concat(blocks)) == 250


def test_surrogate_pk_is_the_global_position() -> None:
    ids = list(_concat(_gen(total_rows=250, chunk_rows=100))["customer_id"])
    assert ids == list(range(250))  # 0..249 across chunks, unique, source 9000.. gone


def test_shared_key_is_reserved_plus_global_position() -> None:
    blocks = _gen(total_rows=120, chunk_rows=50, shared_keys=("customer_id",), reserved=1000)
    ids = list(_concat(blocks)["customer_id"])
    assert ids == list(range(1000, 1120))  # shared key wins: reserved + global position


def test_same_seed_and_chunk_rows_is_byte_identical() -> None:
    a = _concat(_gen(total_rows=170, chunk_rows=64, seed=11))
    b = _concat(_gen(total_rows=170, chunk_rows=64, seed=11))
    pd.testing.assert_frame_equal(a, b)


def test_leakage_gate_runs_per_block() -> None:
    emails = set(_concat(_gen(total_rows=180, chunk_rows=40, seed=5))["email"])
    assert emails.isdisjoint(_REAL_EMAILS)  # zero real sensitive values, block by block


def test_single_chunk_when_chunk_rows_exceeds_total() -> None:
    blocks = _gen(total_rows=30, chunk_rows=10_000, seed=1)
    assert len(blocks) == 1 and len(blocks[0].frame) == 30


def test_empty_table_yields_no_blocks() -> None:
    assert _gen(total_rows=0, chunk_rows=100) == []


def test_chunk_rows_must_be_positive() -> None:
    with pytest.raises(ValueError, match="chunk_rows must be positive"):
        list(generate_table_chunks(_profile(), total_rows=10, seed=1, table="t", chunk_rows=0))


def test_multiple_shared_keys_get_disjoint_ranges() -> None:
    schema = Schema(
        columns=(
            Column("account_id", LogicalType.INTEGER, primary_key=True),
            Column("org_id", LogicalType.INTEGER),
        ),
        primary_key=("account_id",),
    )
    profile = profile_dataset(
        Dataset(frame=pd.DataFrame({"account_id": range(50), "org_id": range(50)}), schema=schema),
        salt="s",
    )
    blocks = list(
        generate_table_chunks(
            profile, total_rows=40, seed=1, table="t", chunk_rows=15,
            shared_keys=("account_id", "org_id"), reserved=100,
        )
    )
    frame = pd.concat([b.frame for b in blocks], ignore_index=True)
    assert list(frame["account_id"]) == list(range(100, 140))  # [reserved, reserved+n)
    assert list(frame["org_id"]) == list(range(140, 180))  # next disjoint sub-range
    assert set(frame["account_id"]).isdisjoint(set(frame["org_id"]))


# --- fail-closed validation (mirrors in-memory apply_shared_keys) ------------


def test_shared_key_not_in_schema_fails_closed() -> None:
    with pytest.raises(KeyspaceError, match="is not in table"):
        list(
            generate_table_chunks(
                _profile(), total_rows=10, seed=1, table="customers", chunk_rows=5,
                shared_keys=("ghost",),
            )
        )


def test_shared_key_that_is_a_foreign_key_fails_closed() -> None:
    schema = Schema(
        columns=(
            Column("id", LogicalType.INTEGER, primary_key=True),
            Column("parent_id", LogicalType.INTEGER),
        ),
        primary_key=("id",),
        foreign_keys=(ForeignKey(("parent_id",), "parents", ("id",)),),
    )
    profile = profile_dataset(
        Dataset(frame=pd.DataFrame({"id": range(20), "parent_id": range(20)}), schema=schema),
        salt="s",
    )
    with pytest.raises(KeyspaceError, match="is a foreign key"):
        list(
            generate_table_chunks(
                profile, total_rows=10, seed=1, table="orders", chunk_rows=5,
                shared_keys=("parent_id",),
            )
        )


def test_composite_pk_is_not_clobbered_to_positions() -> None:
    # A composite integer PK must NOT have each column overwritten with the same global position.
    schema = Schema(
        columns=(
            Column("a", LogicalType.INTEGER, primary_key=True),
            Column("b", LogicalType.INTEGER, primary_key=True),
        ),
        primary_key=("a", "b"),
    )
    profile = profile_dataset(
        Dataset(
            frame=pd.DataFrame({"a": range(5000, 5060), "b": range(7000, 7060)}), schema=schema
        ),
        salt="s",
    )
    frame = pd.concat(
        [b.frame for b in generate_table_chunks(
            profile, total_rows=40, seed=1, table="t", chunk_rows=15)],
        ignore_index=True,
    )
    # not overwritten with 0..n-1, and the two PK columns are not made identical
    assert list(frame["a"]) != list(range(40))
    assert not frame["a"].equals(frame["b"])


def test_chunk_rows_changes_the_fingerprint() -> None:
    a = bootstrap_spec({}, seed=0)
    b = bootstrap_spec({}, seed=0)
    b.chunk_rows = a.chunk_rows + 1
    deps = {"tymi": "1", "numpy": "1", "pandas": "1", "faker": "1"}
    assert consistency_fingerprint(a, deps=deps) != consistency_fingerprint(b, deps=deps)
