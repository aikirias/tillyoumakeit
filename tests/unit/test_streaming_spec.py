"""PRD 1 Phase 2 · P2.3: stream_from_spec + streaming load (AD-22/23/24)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import URL, create_engine, text

from tymi.config.models import ConnectionConfig
from tymi.config.spec import bootstrap_spec
from tymi.core.errors import GenerationError
from tymi.domain.artifacts import (
    Column,
    Dataset,
    ForeignKey,
    GatedDataset,
    LogicalType,
    Schema,
)
from tymi.engines._base import SqlAlchemyEngineAdapter
from tymi.profiling.profiler import profile_dataset
from tymi.synth.streaming import StreamChunk, stream_from_spec

_CUSTOMERS = Schema(
    columns=(
        Column("customer_id", LogicalType.INTEGER, primary_key=True),
        Column("email", LogicalType.STRING),
    ),
    primary_key=("customer_id",),
)
_ORDERS = Schema(
    columns=(
        Column("order_id", LogicalType.INTEGER, primary_key=True),
        Column("customer_id", LogicalType.INTEGER),
        Column("amount", LogicalType.FLOAT),
    ),
    primary_key=("order_id",),
    foreign_keys=(ForeignKey(("customer_id",), "customers", ("customer_id",)),),
)


def _spec(*, seed=3, chunk_rows=30, customer_rows=60, order_rows=100, fixtures=None):
    customers = profile_dataset(
        Dataset(
            frame=pd.DataFrame(
                {"customer_id": range(40), "email": [f"u{i}@x.com" for i in range(40)]}
            ),
            schema=_CUSTOMERS,
        ),
        sensitive_columns=["email"],
        salt="s",
    )
    rng = np.random.default_rng(0)
    orders = profile_dataset(
        Dataset(
            frame=pd.DataFrame(
                {"order_id": range(40), "customer_id": range(40), "amount": rng.normal(0, 1, 40)}
            ),
            schema=_ORDERS,
        ),
        salt="s",
    )
    spec = bootstrap_spec({"customers": customers, "orders": orders}, seed=seed)
    spec.chunk_rows = chunk_rows
    spec.tables["customers"].rows = customer_rows
    spec.tables["customers"].shared_keys = ["customer_id"]
    spec.tables["customers"].reserved_key_block = 1000
    spec.tables["orders"].rows = order_rows
    if fixtures is not None:
        spec.tables["customers"].fixtures = fixtures
    return spec


# --- stream_from_spec (AD-22/23) --------------------------------------------


def test_streams_whole_db_in_fk_order_bounded_and_gated() -> None:
    chunks = list(stream_from_spec(_spec(chunk_rows=30)))
    assert all(isinstance(c, StreamChunk) and isinstance(c.gated, GatedDataset) for c in chunks)
    tables = [c.table for c in chunks]
    # customers (parent) fully streamed before orders (child) — FK-topological order
    assert tables == ["customers"] * 2 + ["orders"] * 4
    assert all(len(c.gated.frame) <= 30 for c in chunks)  # peak memory is one chunk


def test_child_fks_reference_parent_keys_across_chunks() -> None:
    chunks = list(stream_from_spec(_spec(chunk_rows=25)))
    parent_keys = set()
    child_fks = set()
    for c in chunks:
        if c.table == "customers":
            parent_keys.update(c.gated.frame["customer_id"])
        else:
            child_fks.update(c.gated.frame["customer_id"])
    assert parent_keys == set(range(1000, 1060))  # shared keys: reserved + position
    assert child_fks.issubset(parent_keys)  # RI holds across the streamed DB


def test_no_real_sensitive_value_streams() -> None:
    emails = set()
    for c in stream_from_spec(_spec()):
        if c.table == "customers":
            emails.update(c.gated.frame["email"])
    assert emails.isdisjoint({f"u{i}@x.com" for i in range(40)})  # gated per chunk


def test_streaming_is_deterministic() -> None:
    a = list(stream_from_spec(_spec(seed=9)))
    b = list(stream_from_spec(_spec(seed=9)))
    assert [c.table for c in a] == [c.table for c in b]
    for ca, cb in zip(a, b, strict=True):
        pd.testing.assert_frame_equal(ca.gated.frame, cb.gated.frame)


def test_fixtures_fail_closed_on_the_streaming_path() -> None:
    spec = _spec(fixtures=[{"customer_id": 1, "email": "admin@test.dev"}])
    with pytest.raises(GenerationError, match="pins fixtures"):
        list(stream_from_spec(spec))


def test_fk_to_a_second_shared_column_uses_the_right_offset() -> None:
    # customers has TWO shared keys; orders references the SECOND (org_id): base = reserved + rows.
    cust_schema = Schema(
        columns=(
            Column("customer_id", LogicalType.INTEGER, primary_key=True),
            Column("org_id", LogicalType.INTEGER),
        ),
        primary_key=("customer_id",),
    )
    ord_schema = Schema(
        columns=(
            Column("order_id", LogicalType.INTEGER, primary_key=True),
            Column("org_id", LogicalType.INTEGER),
        ),
        primary_key=("order_id",),
        foreign_keys=(ForeignKey(("org_id",), "customers", ("org_id",)),),
    )
    customers = profile_dataset(
        Dataset(
            frame=pd.DataFrame({"customer_id": range(30), "org_id": range(30)}), schema=cust_schema
        ),
        salt="s",
    )
    orders = profile_dataset(
        Dataset(
            frame=pd.DataFrame({"order_id": range(30), "org_id": range(30)}), schema=ord_schema
        ),
        salt="s",
    )
    spec = bootstrap_spec({"customers": customers, "orders": orders}, seed=1)
    spec.chunk_rows = 20
    spec.tables["customers"].rows = 50
    spec.tables["customers"].shared_keys = ["customer_id", "org_id"]  # org_id is index 1
    spec.tables["customers"].reserved_key_block = 1000
    spec.tables["orders"].rows = 40
    org_fks = set()
    for c in stream_from_spec(spec):
        if c.table == "orders":
            org_fks.update(c.gated.frame["org_id"])
    # org_id keyspace: reserved + col_index(1)*rows(50) + [0,50) = [1050, 1100)
    assert org_fks.issubset(set(range(1050, 1100)))


def test_natural_key_fk_parent_fails_closed() -> None:
    # orders FK references customers.email (a natural key, not position-addressable) -> fail closed.
    orders_schema = Schema(
        columns=(
            Column("order_id", LogicalType.INTEGER, primary_key=True),
            Column("cust_email", LogicalType.STRING),
        ),
        primary_key=("order_id",),
        foreign_keys=(ForeignKey(("cust_email",), "customers", ("email",)),),
    )
    customers = profile_dataset(
        Dataset(
            frame=pd.DataFrame({"customer_id": range(20), "email": [f"u{i}@x" for i in range(20)]}),
            schema=_CUSTOMERS,
        ),
        salt="s",
    )
    orders = profile_dataset(
        Dataset(
            frame=pd.DataFrame(
                {"order_id": range(20), "cust_email": [f"u{i}@x" for i in range(20)]}
            ),
            schema=orders_schema,
        ),
        salt="s",
    )
    spec = bootstrap_spec({"customers": customers, "orders": orders}, seed=1)
    spec.tables["customers"].rows = 20
    spec.tables["orders"].rows = 20
    with pytest.raises(GenerationError, match="no.+position-addressable rule"):
        list(stream_from_spec(spec))


# --- streaming load: replace-first, append-rest, idempotent (AD-24) ----------


class _SqliteAdapter(SqlAlchemyEngineAdapter):
    DIALECT = "sqlite"

    def __init__(self, path: str) -> None:
        super().__init__(ConnectionConfig(host="mem", port=1, user_env="U", password_env="P"))
        self._path = path

    def build_url(self):  # type: ignore[override]
        return URL.create("sqlite", database=self._path)


def _chunks(schema, *frames):
    return [Dataset(frame=f, schema=schema) for f in frames]


def test_zero_row_table_streams_one_empty_chunk() -> None:
    # A rows=0 table must still yield a chunk so the destination is truncated (no stale rows).
    spec = _spec(customer_rows=0, order_rows=0)
    by_table: dict[str, int] = {}
    for c in stream_from_spec(spec):
        by_table[c.table] = by_table.get(c.table, 0) + 1
        assert len(c.gated.frame) == 0
    assert by_table == {"customers": 1, "orders": 1}  # one empty chunk each, table materialised


def test_load_stream_empty_chunk_replaces_to_zero_rows(tmp_path) -> None:
    db = tmp_path / "e.db"
    adapter = _SqliteAdapter(str(db))
    schema = Schema(columns=(Column("id", LogicalType.INTEGER),))
    adapter.load_stream(_chunks(schema, pd.DataFrame({"id": [0, 1, 2]})), table="nums")
    # a re-run with a single EMPTY chunk truncates the table to 0 rows (idempotent)
    empty = _chunks(schema, pd.DataFrame({"id": []}, dtype="int64"))
    written = adapter.load_stream(empty, table="nums")
    assert written == 0
    engine = create_engine(f"sqlite:///{db}")
    try:
        with engine.begin() as conn:
            count = conn.execute(text("select count(*) from nums")).scalar()
        assert count == 0  # stale rows gone
    finally:
        engine.dispose()


def test_load_stream_creates_then_appends_and_is_idempotent(tmp_path) -> None:
    db = tmp_path / "t.db"
    adapter = _SqliteAdapter(str(db))
    schema = Schema(columns=(Column("id", LogicalType.INTEGER),))
    frames = [pd.DataFrame({"id": [0, 1]}), pd.DataFrame({"id": [2, 3]}), pd.DataFrame({"id": [4]})]

    written = adapter.load_stream(_chunks(schema, *frames), table="nums")
    assert written == 5

    engine = create_engine(f"sqlite:///{db}")
    try:
        with engine.begin() as conn:
            got = [r[0] for r in conn.execute(text("select id from nums order by id"))]
        assert got == [0, 1, 2, 3, 4]  # first chunk replaced, the rest appended
        # re-running truncates-then-writes (idempotent) — not doubled
        adapter.load_stream(_chunks(schema, *frames), table="nums")
        with engine.begin() as conn:
            count = conn.execute(text("select count(*) from nums")).scalar()
        assert count == 5
    finally:
        engine.dispose()
