"""PRD 1 Story 3.1: pinned fixtures with scan-and-reject (AD-17)."""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd
import pytest

from tymi.config.spec import bootstrap_spec
from tymi.core.errors import FixtureError, LeakageError
from tymi.domain.artifacts import (
    Column,
    Dataset,
    ForeignKey,
    GatedDataset,
    LeakageGuard,
    LogicalType,
    Schema,
    leakage_digest,
    require_gated,
)
from tymi.privacy.classifier import classify_sensitive_columns
from tymi.profiling.profiler import profile_dataset
from tymi.synth.fixtures import overlay_fixtures
from tymi.synth.leakage import scan_and_gate
from tymi.synth.whole_db import generate_from_spec

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
    ),
    primary_key=("order_id",),
    foreign_keys=(ForeignKey(("customer_id",), "customers", ("customer_id",)),),
)


def _customers(n=10, start=100):
    return Dataset(
        frame=pd.DataFrame(
            {"customer_id": range(start, start + n), "email": [f"g{i}@synth.dev" for i in range(n)]}
        ),
        schema=_CUSTOMERS_SCHEMA,
    )


# --- overlay: verbatim, reserved block, FK-consistency ----------------------


def test_fixtures_overlaid_verbatim_in_reserved_block() -> None:
    fixtures = [{"customer_id": 1, "email": "admin@test.dev"}]
    out, masks = overlay_fixtures(
        {"customers": _customers()},
        fixtures_by_table={"customers": fixtures},
        reserved_by_table={"customers": 50},
    )
    frame = out["customers"].frame
    assert len(frame) == 11  # 10 generated + 1 fixture
    fixture_row = frame[masks["customers"]]
    assert list(fixture_row["customer_id"]) == [1]  # verbatim, in [0, 50)
    assert list(fixture_row["email"]) == ["admin@test.dev"]  # exempt from regeneration
    # generated keys (>= reserved) never collide with the fixture key (< reserved)
    assert set(frame[~masks["customers"]]["customer_id"]).isdisjoint({1})


def test_fixture_key_outside_reserved_block_fails_closed() -> None:
    with pytest.raises(FixtureError, match="outside the reserved block"):
        overlay_fixtures(
            {"customers": _customers()},
            fixtures_by_table={"customers": [{"customer_id": 999, "email": "x@test.dev"}]},
            reserved_by_table={"customers": 50},
        )


def test_fixture_string_pk_fails_closed_cleanly() -> None:
    # A non-integer PK fixture must fail closed as a FixtureError, not a raw TypeError.
    schema = Schema(
        columns=(Column("code", LogicalType.STRING, primary_key=True),),
        primary_key=("code",),
    )
    ds = Dataset(frame=pd.DataFrame({"code": ["gen-1", "gen-2"]}), schema=schema)
    with pytest.raises(FixtureError, match="must be an integer"):
        overlay_fixtures(
            {"t": ds},
            fixtures_by_table={"t": [{"code": "fixture-a"}]},
            reserved_by_table={"t": 50},
        )


def test_fixture_key_colliding_with_generated_pk_fails_closed() -> None:
    # If a fixture key duplicates a generated PK (bad reserved block), fail closed (PDE-10).
    ds = _customers(n=5, start=0)  # generated customer_id 0..4
    with pytest.raises(FixtureError, match="collide with a generated primary key"):
        overlay_fixtures(
            {"customers": ds},
            fixtures_by_table={"customers": [{"customer_id": 3, "email": "x@test.dev"}]},
            reserved_by_table={"customers": 50},  # 3 is in [0,50) but also a generated key
        )


def test_fixture_unknown_column_fails_closed() -> None:
    with pytest.raises(FixtureError, match="unknown column"):
        overlay_fixtures(
            {"customers": _customers()},
            fixtures_by_table={"customers": [{"customer_id": 1, "bogus": 1}]},
            reserved_by_table={"customers": 50},
        )


def test_fixture_fk_without_parent_fails_closed() -> None:
    with pytest.raises(FixtureError, match="no row in parent"):
        overlay_fixtures(
            {"customers": _customers(), "orders": Dataset(
                frame=pd.DataFrame({"order_id": [200], "customer_id": [150]}),
                schema=_ORDERS_SCHEMA,
            )},
            fixtures_by_table={"orders": [{"order_id": 5, "customer_id": 77}]},  # no such customer
            reserved_by_table={"orders": 50},
        )


def test_fixture_fk_referencing_a_fixture_parent_is_ok() -> None:
    out, masks = overlay_fixtures(
        {
            "customers": _customers(),
            "orders": Dataset(
                frame=pd.DataFrame({"order_id": [200], "customer_id": [150]}),
                schema=_ORDERS_SCHEMA,
            ),
        },
        fixtures_by_table={
            "customers": [{"customer_id": 1, "email": "a@test.dev"}],
            "orders": [{"order_id": 5, "customer_id": 1}],  # references the fixture customer
        },
        reserved_by_table={"customers": 50, "orders": 50},
    )
    assert masks["orders"].sum() == 1


def test_attestation_is_logged(caplog) -> None:
    with caplog.at_level(logging.INFO, logger="tymi.provision.fixtures"):
        overlay_fixtures(
            {"customers": _customers()},
            fixtures_by_table={"customers": [{"customer_id": 1, "email": "a@test.dev"}]},
            reserved_by_table={"customers": 50},
        )
    assert any("fixture attestation" in r.message for r in caplog.records)


# --- scan-and-reject: never regenerate, fail closed on real value / PII ------


def _guard_with_real(value: str, salt="s") -> LeakageGuard:
    return LeakageGuard(salt=salt, columns={"email": (leakage_digest(value, salt),)})


def test_scan_rejects_a_real_value_in_a_fixture_no_regeneration() -> None:
    # a fixture whose email equals a REAL source value must fail closed (not be regenerated).
    frame = pd.DataFrame({"customer_id": [100, 1], "email": ["g@synth.dev", "real@corp.com"]})
    ds = Dataset(frame=frame, schema=_CUSTOMERS_SCHEMA)
    mask = np.array([False, True])
    with pytest.raises(LeakageError, match="collide with a real source value"):
        scan_and_gate(ds, _guard_with_real("real@corp.com"), fixture_mask=mask)


def test_scan_rejects_unguarded_pii_in_a_fixture() -> None:
    # 'notes' is NOT guarded; a fixture smuggling an SSN into it is un-guarded PII -> fail closed.
    schema = Schema(
        columns=(
            Column("customer_id", LogicalType.INTEGER, primary_key=True),
            Column("notes", LogicalType.STRING),
        ),
        primary_key=("customer_id",),
    )
    frame = pd.DataFrame({"customer_id": [100, 1], "notes": ["hello world", "123-45-6789"]})
    ds = Dataset(frame=frame, schema=schema)
    mask = np.array([False, True])
    with pytest.raises(LeakageError, match="un-guarded PII"):
        scan_and_gate(ds, None, fixture_mask=mask, classify=classify_sensitive_columns)


def test_scan_rejects_real_value_in_a_structural_shared_column() -> None:
    # A fixture verbatim value in a STRUCTURAL (shared/PK) column is still scanned against the
    # full guard — generated rows skip structural columns, but fixtures must not smuggle a real
    # value through one. (Regression for the shared/key-column bypass.)
    guard = LeakageGuard(salt="s", columns={"customer_id": (leakage_digest(4242, "s"),)})
    frame = pd.DataFrame({"customer_id": [100, 4242], "email": ["g@synth.dev", "a@test.dev"]})
    ds = Dataset(frame=frame, schema=_CUSTOMERS_SCHEMA)
    mask = np.array([False, True])
    with pytest.raises(LeakageError, match="fixture value"):
        scan_and_gate(ds, guard, fixture_mask=mask, structural_columns={"customer_id"})


def test_scan_rejects_minority_pii_among_fixture_rows() -> None:
    # One PII cell among several fixture rows must trip the scan (no minority-row bypass).
    schema = Schema(
        columns=(
            Column("customer_id", LogicalType.INTEGER, primary_key=True),
            Column("notes", LogicalType.STRING),
        ),
        primary_key=("customer_id",),
    )
    frame = pd.DataFrame(
        {
            "customer_id": [100, 1, 2, 3],
            "notes": ["hi", "hello there", "just text", "123-45-6789"],  # 1 SSN of 3 fixtures
        }
    )
    ds = Dataset(frame=frame, schema=schema)
    mask = np.array([False, True, True, True])
    with pytest.raises(LeakageError, match="un-guarded PII"):
        scan_and_gate(ds, None, fixture_mask=mask, classify=classify_sensitive_columns)


def test_scan_accepts_a_synthetic_fixture_and_mints_gated_dataset() -> None:
    frame = pd.DataFrame({"customer_id": [100, 1], "email": ["g@synth.dev", "admin@test.dev"]})
    ds = Dataset(frame=frame, schema=_CUSTOMERS_SCHEMA)
    mask = np.array([False, True])
    out = scan_and_gate(
        ds,
        _guard_with_real("real@corp.com"),
        fixture_mask=mask,
        classify=classify_sensitive_columns,
    )
    assert isinstance(out, GatedDataset)
    require_gated(out)  # accepted at the load boundary


# --- end-to-end through generate_from_spec ----------------------------------


def _spec_with_fixture(email="login@test.dev"):
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
    spec = bootstrap_spec({"customers": customers}, seed=3)
    ts = spec.tables["customers"]
    ts.shared_keys = ["customer_id"]
    ts.reserved_key_block = 100
    ts.fixtures = [{"customer_id": 7, "email": email}]
    return spec


def test_generate_from_spec_overlays_fixture_and_seals() -> None:
    out = generate_from_spec(_spec_with_fixture())
    frame = out["customers"].frame
    assert isinstance(out["customers"], GatedDataset)
    assert 7 in set(frame["customer_id"])  # fixture present verbatim, in the reserved block
    assert "login@test.dev" in set(frame["email"])
    generated = frame[frame["customer_id"] >= 100]["customer_id"]
    assert 7 not in set(generated)  # generated keys never collide with the fixture key


def test_generate_from_spec_rejects_fixture_with_real_source_value() -> None:
    # fixture email 'u0@x.com' IS a real source value -> the seal scan fails closed.
    with pytest.raises(LeakageError):
        generate_from_spec(_spec_with_fixture(email="u0@x.com"))
