"""PRD 1 Story 1.3: whole-DB faithful generation from a Spec (AD-13/AD-21)."""

from __future__ import annotations

import pandas as pd
import pytest

from tymi.config.spec import bootstrap_spec
from tymi.core.errors import GenerationError
from tymi.domain.artifacts import (
    Column,
    Dataset,
    ForeignKey,
    GatedDataset,
    LogicalType,
    Schema,
    require_gated,
)
from tymi.profiling.profiler import profile_dataset
from tymi.synth.whole_db import generate_from_spec

_CUSTOMERS_SCHEMA = Schema(
    columns=(
        Column("id", LogicalType.INTEGER, primary_key=True),
        Column("email", LogicalType.STRING),
    ),
    primary_key=("id",),
)
_ORDERS_SCHEMA = Schema(
    columns=(
        Column("id", LogicalType.INTEGER, primary_key=True),
        Column("customer_id", LogicalType.INTEGER),
        Column("amount", LogicalType.FLOAT),
    ),
    primary_key=("id",),
    foreign_keys=(ForeignKey(("customer_id",), "customers", ("id",)),),
)

_REAL_EMAILS = [f"real.person{i}@corp.example" for i in range(40)]


def _spec(seed: int = 7):
    customers = profile_dataset(
        Dataset(
            frame=pd.DataFrame({"id": range(40), "email": _REAL_EMAILS}),
            schema=_CUSTOMERS_SCHEMA,
        ),
        sensitive_columns=["email"],
        salt="s",
    )
    orders = profile_dataset(
        Dataset(
            frame=pd.DataFrame(
                {
                    "id": range(60),
                    "customer_id": [i % 40 for i in range(60)],
                    "amount": [float(i) for i in range(60)],
                }
            ),
            schema=_ORDERS_SCHEMA,
        ),
        salt="s",
    )
    return bootstrap_spec({"customers": customers, "orders": orders}, seed=seed)


def test_generates_every_table_as_gated_dataset_with_pinned_rows() -> None:
    result = generate_from_spec(_spec())
    assert set(result) == {"customers", "orders"}
    for gd in result.values():
        assert isinstance(gd, GatedDataset)
        require_gated(gd)  # accepted at the load boundary
    assert len(result["customers"].frame) == 40  # pinned from the Profile's row_count
    assert len(result["orders"].frame) == 60


def test_referential_integrity_holds_across_tables() -> None:
    result = generate_from_spec(_spec())
    parent_ids = set(result["customers"].frame["id"])
    child_fks = set(result["orders"].frame["customer_id"])
    assert child_fks <= parent_ids  # every FK points at a real generated parent key


def test_no_real_sensitive_value_leaks() -> None:
    # The sensitive email column is gated DB-wide: no real source email survives (PDE-7).
    result = generate_from_spec(_spec())
    generated = set(result["customers"].frame["email"])
    assert generated.isdisjoint(_REAL_EMAILS)


def test_same_spec_and_seed_is_byte_identical() -> None:
    a = generate_from_spec(_spec(seed=11))
    b = generate_from_spec(_spec(seed=11))
    assert set(a) == set(b)
    for name in a:
        pd.testing.assert_frame_equal(a[name].frame, b[name].frame)
        assert a[name].schema == b[name].schema


def test_different_seed_diverges() -> None:
    a = generate_from_spec(_spec(seed=1))
    b = generate_from_spec(_spec(seed=2))
    # At least one table's content differs — the seed actually drives generation.
    assert not a["orders"].frame.equals(b["orders"].frame)


def test_fk_parent_missing_fails_closed() -> None:
    # A partial spec (child without its FK parent) must fail closed, not emit dangling FKs.
    orders = profile_dataset(
        Dataset(
            frame=pd.DataFrame(
                {
                    "id": range(20),
                    "customer_id": [i % 10 for i in range(20)],
                    "amount": [float(i) for i in range(20)],
                }
            ),
            schema=_ORDERS_SCHEMA,
        ),
        salt="s",
    )
    spec = bootstrap_spec({"orders": orders}, seed=1)  # 'customers' deliberately absent
    with pytest.raises(GenerationError, match="not in the spec"):
        generate_from_spec(spec)


def test_sensitive_primary_key_colliding_with_surrogate_does_not_corrupt() -> None:
    # A sensitive integer PK whose real values (0..n-1) collide with the synthetic surrogate
    # arange: the seal must NOT regenerate the structural key (which would break uniqueness or
    # raise). PKs stay unique and generation succeeds. (Sensitive keys proper are Epic 2.)
    schema = Schema(
        columns=(
            Column("user_id", LogicalType.INTEGER, primary_key=True),
            Column("note", LogicalType.STRING),
        ),
        primary_key=("user_id",),
    )
    profile = profile_dataset(
        Dataset(
            frame=pd.DataFrame({"user_id": range(30), "note": [f"n{i}" for i in range(30)]}),
            schema=schema,
        ),
        sensitive_columns=["user_id"],  # PK marked sensitive; real ids 0..29 overlap arange(30)
        salt="s",
    )
    result = generate_from_spec(bootstrap_spec({"users": profile}, seed=4))
    pks = result["users"].frame["user_id"]
    assert pks.is_unique and len(pks) == 30  # structural key intact, no LeakageError
