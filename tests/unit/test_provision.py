"""PRD 1 Story 3.3: the provisioning pipeline + report (AD-19, PDE-13/15)."""

from __future__ import annotations

import pandas as pd
import pytest

from tymi.config.spec import DestinationSpec, bootstrap_spec
from tymi.core.errors import EngineError, GenerationError, GuardrailError
from tymi.domain.artifacts import Column, Dataset, ForeignKey, LogicalType, Schema
from tymi.profiling.profiler import profile_dataset
from tymi.provision.guardrail import NONPROD
from tymi.provision.pipeline import ProvisionReport, provision

_CUSTOMERS_SCHEMA = Schema(
    columns=(
        Column("customer_id", LogicalType.INTEGER, primary_key=True),
        Column("email", LogicalType.STRING),
    ),
    primary_key=("customer_id",),
)
_ORDERS_SCHEMA = Schema(
    columns=(
        Column("order_id", LogicalType.INTEGER, primary_key=True),
        Column("customer_id", LogicalType.INTEGER),
        Column("amount", LogicalType.FLOAT),
    ),
    primary_key=("order_id",),
    foreign_keys=(ForeignKey(("customer_id",), "customers", ("customer_id",)),),
)


class _FakeAdapter:
    """A destination adapter that records every load call instead of touching a DB."""

    supports_write = True

    def __init__(self) -> None:
        self.loaded: list[tuple[str, pd.DataFrame]] = []
        self.streamed: list[tuple[str, list[pd.DataFrame]]] = []

    def load(self, dataset, *, table: str) -> None:
        self.loaded.append((table, dataset.frame.copy(deep=True)))

    def load_stream(self, chunks, *, table: str) -> int:
        frames = [ds.frame.copy(deep=True) for ds in chunks]  # consumes the iterator one at a time
        self.streamed.append((table, frames))
        return sum(len(f) for f in frames)

    def streamed_frame(self, table: str) -> pd.DataFrame:
        frames = [f for t, group in self.streamed if t == table for f in group]
        return pd.concat(frames, ignore_index=True)


class _ReadOnlyAdapter:
    supports_write = False

    def load(self, dataset, *, table: str) -> None:  # pragma: no cover - should never be called
        raise AssertionError("read-only adapter must never be loaded")


def _spec(*, environment=NONPROD, host="dev-db", database="app_dev", fixtures=None, seed=3):
    profile = profile_dataset(
        Dataset(
            frame=pd.DataFrame(
                {"customer_id": range(20), "email": [f"u{i}@x.com" for i in range(20)]}
            ),
            schema=_CUSTOMERS_SCHEMA,
        ),
        sensitive_columns=["email"],
        salt="s",
    )
    spec = bootstrap_spec({"customers": profile}, seed=seed)
    spec.destination = DestinationSpec(environment=environment, host=host, database=database)
    if fixtures is not None:
        ts = spec.tables["customers"]
        ts.reserved_key_block = 100
        ts.shared_keys = ["customer_id"]
        ts.fixtures = fixtures
    return spec


# --- happy path (AD-19 pipeline + PDE-15 report) ----------------------------


def test_provision_loads_every_table_and_reports() -> None:
    adapter = _FakeAdapter()
    report = provision(_spec(), adapter)
    assert isinstance(report, ProvisionReport)
    assert [t for t, _ in adapter.loaded] == ["customers"]  # loaded via EngineAdapter.load
    assert report.environment == NONPROD
    assert len(report.fingerprint) == 64  # blake2b-256 hex
    (table,) = report.tables
    assert table.table == "customers" and table.rows == 20
    assert "email" in table.gated_columns  # gate result recorded (PDE-15)


def test_report_includes_fixtures_and_renders() -> None:
    adapter = _FakeAdapter()
    report = provision(_spec(fixtures=[{"customer_id": 7, "email": "admin@test.dev"}]), adapter)
    (table,) = report.tables
    assert table.rows == 21 and table.fixtures == 1  # 20 generated + 1 fixture
    text = report.render()
    assert "customers" in text and report.fingerprint in text and "fixtures=1" in text


# --- guardrail runs first, fails closed before any write (AD-18) -------------


def test_prod_destination_fails_closed_before_any_load() -> None:
    adapter = _FakeAdapter()
    with pytest.raises(GuardrailError):
        provision(_spec(host="prod-db-01"), adapter)
    assert adapter.loaded == []  # nothing was written


def test_missing_destination_fails_closed() -> None:
    spec = _spec()
    spec.destination = None
    adapter = _FakeAdapter()
    with pytest.raises(GuardrailError):
        provision(spec, adapter)
    assert adapter.loaded == []


def test_read_only_adapter_is_rejected() -> None:
    with pytest.raises(EngineError, match="does not support write"):
        provision(_spec(), _ReadOnlyAdapter())


# --- idempotency / determinism (NFR-F, PDE-11) ------------------------------


def test_provision_is_deterministic_across_runs() -> None:
    # Same spec+seed → same fingerprint AND byte-identical loaded frames (idempotent replace).
    a, b = _FakeAdapter(), _FakeAdapter()
    report_a = provision(_spec(seed=9), a)
    report_b = provision(_spec(seed=9), b)
    assert report_a.fingerprint == report_b.fingerprint
    pd.testing.assert_frame_equal(a.loaded[0][1], b.loaded[0][1])


def test_only_gated_data_is_loaded() -> None:
    # The pipeline routes every table through require_gated before load; the loaded frame is the
    # sealed content, and a real source email never appears in the loaded destination table.
    adapter = _FakeAdapter()
    provision(_spec(), adapter)
    loaded_emails = set(adapter.loaded[0][1]["email"])
    assert loaded_emails.isdisjoint({f"u{i}@x.com" for i in range(20)})  # zero real values


# --- out-of-core streaming provision (Phase 2, AD-22..24, PDE-13) -----------


def _streamable_spec(*, seed=3, chunk_rows=8, customer_rows=20, order_rows=30):
    customers = profile_dataset(
        Dataset(
            frame=pd.DataFrame(
                {"customer_id": range(20), "email": [f"u{i}@x.com" for i in range(20)]}
            ),
            schema=_CUSTOMERS_SCHEMA,
        ),
        sensitive_columns=["email"],
        salt="s",
    )
    orders = profile_dataset(
        Dataset(
            frame=pd.DataFrame(
                {
                    "order_id": range(20),
                    "customer_id": range(20),
                    "amount": [float(i) for i in range(20)],
                }
            ),
            schema=_ORDERS_SCHEMA,
        ),
        salt="s",
    )
    spec = bootstrap_spec({"customers": customers, "orders": orders}, seed=seed)
    spec.destination = DestinationSpec(environment=NONPROD, host="dev-db", database="app")
    spec.chunk_rows = chunk_rows
    spec.tables["customers"].rows = customer_rows
    spec.tables["customers"].shared_keys = ["customer_id"]
    spec.tables["customers"].reserved_key_block = 1000
    spec.tables["orders"].rows = order_rows
    return spec


def test_stream_provision_writes_via_load_stream_and_aggregates() -> None:
    adapter = _FakeAdapter()
    report = provision(_streamable_spec(), adapter, stream=True)
    assert adapter.loaded == []  # in-memory path not used
    assert [t for t, _ in adapter.streamed] == ["customers", "orders"]  # FK-topological order
    rows = {t.table: t.rows for t in report.tables}
    assert rows == {"customers": 20, "orders": 30}  # aggregated across chunks
    # the report carries a per-table fidelity (sampled on the first chunk) + gated columns
    orders_line = next(t for t in report.tables if t.table == "orders")
    assert orders_line.fidelity_correlation is not None  # scored on the first streamed chunk
    customers_line = next(t for t in report.tables if t.table == "customers")
    assert "email" in customers_line.gated_columns


def test_stream_peak_memory_is_one_chunk() -> None:
    adapter = _FakeAdapter()
    provision(_streamable_spec(chunk_rows=8, customer_rows=20), adapter, stream=True)
    sizes = [len(f) for t, group in adapter.streamed for f in group]
    assert max(sizes) <= 8  # every written chunk is bounded by chunk_rows


def test_stream_referential_integrity_holds() -> None:
    adapter = _FakeAdapter()
    provision(_streamable_spec(), adapter, stream=True)
    parent_keys = set(adapter.streamed_frame("customers")["customer_id"])
    child_fks = set(adapter.streamed_frame("orders")["customer_id"])
    assert parent_keys == set(range(1000, 1020))  # shared keys
    assert child_fks.issubset(parent_keys)  # RI across the streamed DB


def test_stream_only_gated_data_is_written() -> None:
    adapter = _FakeAdapter()
    provision(_streamable_spec(), adapter, stream=True)
    emails = set(adapter.streamed_frame("customers")["email"])
    assert emails.isdisjoint({f"u{i}@x.com" for i in range(20)})  # zero real values, per chunk


def test_stream_guardrail_fails_closed_before_any_write() -> None:
    spec = _streamable_spec()
    spec.destination = DestinationSpec(environment=NONPROD, host="prod-db-01", database="app")
    adapter = _FakeAdapter()
    with pytest.raises(GuardrailError):
        provision(spec, adapter, stream=True)
    assert adapter.streamed == []  # nothing written


def test_stream_fixtures_fail_closed() -> None:
    spec = _streamable_spec()
    spec.tables["customers"].fixtures = [{"customer_id": 1, "email": "admin@test.dev"}]
    with pytest.raises(GenerationError, match="pins fixtures"):
        provision(spec, _FakeAdapter(), stream=True)


def test_stream_and_in_memory_have_different_fingerprints() -> None:
    # The two engines partition substreams differently -> different bytes -> the fingerprint must
    # differ so it never claims two different realities are the same (mode is in the unit).
    spec = _streamable_spec()
    streamed = provision(spec, _FakeAdapter(), stream=True)
    in_memory = provision(spec, _FakeAdapter(), stream=False)
    assert streamed.fingerprint != in_memory.fingerprint


def test_stream_is_deterministic() -> None:
    a, b = _FakeAdapter(), _FakeAdapter()
    fa = provision(_streamable_spec(seed=11), a, stream=True)
    fb = provision(_streamable_spec(seed=11), b, stream=True)
    assert fa.fingerprint == fb.fingerprint
    pd.testing.assert_frame_equal(a.streamed_frame("orders"), b.streamed_frame("orders"))
