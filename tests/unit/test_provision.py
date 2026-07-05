"""PRD 1 Story 3.3: the provisioning pipeline + report (AD-19, PDE-13/15)."""

from __future__ import annotations

import pandas as pd
import pytest

from tymi.config.spec import DestinationSpec, bootstrap_spec
from tymi.core.errors import EngineError, GuardrailError
from tymi.domain.artifacts import Column, Dataset, LogicalType, Schema
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


class _FakeAdapter:
    """A destination adapter that records every load call instead of touching a DB."""

    supports_write = True

    def __init__(self) -> None:
        self.loaded: list[tuple[str, pd.DataFrame]] = []

    def load(self, dataset, *, table: str) -> None:
        self.loaded.append((table, dataset.frame.copy(deep=True)))


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
