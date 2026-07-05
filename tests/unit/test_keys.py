"""PRD 1 Story 2.2: position-derived shared keys + reserved fixture keyspace (AD-16, OQ-5)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tymi.config.spec import bootstrap_spec
from tymi.core.errors import KeyspaceError
from tymi.domain.artifacts import (
    Column,
    Dataset,
    ForeignKey,
    LogicalType,
    Schema,
)
from tymi.profiling.profiler import profile_dataset
from tymi.synth.keys import apply_shared_keys, position_keys
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
        Column("id", LogicalType.INTEGER, primary_key=True),
        Column("customer_id", LogicalType.INTEGER),
    ),
    primary_key=("id",),
    foreign_keys=(ForeignKey(("customer_id",), "customers", ("customer_id",)),),
)


def _customers(n=20):
    return Dataset(
        frame=pd.DataFrame(
            {"customer_id": range(1000, 1000 + n), "email": [f"c{i}@x.com" for i in range(n)]}
        ),
        schema=_CUSTOMERS_SCHEMA,
    )


def _orders(n=40, parent_n=20):
    return Dataset(
        frame=pd.DataFrame(
            {"id": range(n), "customer_id": [1000 + (i % parent_n) for i in range(n)]}
        ),
        schema=_ORDERS_SCHEMA,
    )


# --- the keyer primitive -----------------------------------------------------


def test_position_keys_start_at_reserved_block() -> None:
    assert np.array_equal(position_keys(0, 4), np.array([0, 1, 2, 3]))
    assert np.array_equal(position_keys(500, 3), np.array([500, 501, 502]))


# --- shared-key emission + FK remap -----------------------------------------


def test_shared_pk_becomes_position_derived_and_remaps_fks() -> None:
    datasets = {"customers": _customers(20), "orders": _orders(40, 20)}
    out = apply_shared_keys(
        datasets,
        shared_by_table={"customers": ["customer_id"], "orders": []},
        reserved_by_table={"customers": 100, "orders": 0},
    )
    # parent shared key is position-derived from the reserved block, not the source 1000..1019
    assert list(out["customers"].frame["customer_id"]) == list(range(100, 120))
    # child FKs were remapped so referential integrity still holds against the NEW keys
    parent_keys = set(out["customers"].frame["customer_id"])
    assert set(out["orders"].frame["customer_id"]).issubset(parent_keys)
    assert set(out["orders"].frame["customer_id"]) == set(range(100, 120))


def test_two_shared_columns_get_distinct_ranges() -> None:
    # Two independent shared entity ids in one table must NOT collapse to identical values.
    schema = Schema(
        columns=(
            Column("account_id", LogicalType.INTEGER, primary_key=True),
            Column("org_id", LogicalType.INTEGER),
        ),
        primary_key=("account_id",),
    )
    ds = Dataset(
        frame=pd.DataFrame({"account_id": range(100, 105), "org_id": range(200, 205)}),
        schema=schema,
    )
    out = apply_shared_keys(
        {"t": ds},
        shared_by_table={"t": ["account_id", "org_id"]},
        reserved_by_table={"t": 10},
    )
    acct = list(out["t"].frame["account_id"])
    org = list(out["t"].frame["org_id"])
    assert acct == list(range(10, 15))  # first column: [reserved, reserved+n)
    assert org == list(range(15, 20))  # second column: packed into the next disjoint sub-range
    assert acct != org  # independent, not collapsed


def test_non_unique_shared_column_fails_closed() -> None:
    schema = Schema(columns=(Column("region", LogicalType.INTEGER),))
    ds = Dataset(frame=pd.DataFrame({"region": [1, 1, 2]}), schema=schema)
    with pytest.raises(KeyspaceError, match="has duplicate values"):
        apply_shared_keys(
            {"t": ds}, shared_by_table={"t": ["region"]}, reserved_by_table={"t": 0}
        )


def test_sharing_part_of_composite_key_fails_closed() -> None:
    parent = Dataset(
        frame=pd.DataFrame({"a": [1, 1, 2], "b": [10, 20, 10]}),
        schema=Schema(
            columns=(Column("a", LogicalType.INTEGER), Column("b", LogicalType.INTEGER)),
            primary_key=("a", "b"),
        ),
    )
    child = Dataset(
        frame=pd.DataFrame({"ca": [1, 2], "cb": [10, 10]}),
        schema=Schema(
            columns=(Column("ca", LogicalType.INTEGER), Column("cb", LogicalType.INTEGER)),
            foreign_keys=(ForeignKey(("ca", "cb"), "parent", ("a", "b")),),
        ),
    )
    with pytest.raises(KeyspaceError, match="composite foreign-key reference"):
        apply_shared_keys(
            {"parent": parent, "child": child},
            shared_by_table={"parent": ["a"]},  # only half of the composite PK
            reserved_by_table={"parent": 0},
        )


def test_inputs_not_mutated() -> None:
    datasets = {"customers": _customers(5), "orders": _orders(10, 5)}
    apply_shared_keys(
        datasets,
        shared_by_table={"customers": ["customer_id"]},
        reserved_by_table={"customers": 0},
    )
    assert list(datasets["customers"].frame["customer_id"]) == list(range(1000, 1005))  # untouched


# --- cross-team identity: source- and seed-independent ----------------------


def test_shared_keys_are_source_and_seed_independent() -> None:
    # Two "teams": different source values AND different seeds, same pinned row counts.
    team_a = generate_from_spec(_spec_with_shared(seed=1, source_start=1000))
    team_b = generate_from_spec(_spec_with_shared(seed=999, source_start=7_000_000))
    # the shared entity key matches exactly across teams despite different source + seed
    assert list(team_a["customers"].frame["customer_id"]) == list(
        team_b["customers"].frame["customer_id"]
    )


def test_shared_pk_remaps_child_fks_end_to_end() -> None:
    # Through generate_from_spec: a shared PK is position-derived AND the child's FK still joins.
    customers = profile_dataset(
        Dataset(
            frame=pd.DataFrame(
                {"customer_id": range(5000, 5020), "email": [f"c{i}@x.com" for i in range(20)]}
            ),
            schema=_CUSTOMERS_SCHEMA,
        ),
        salt="s",
    )
    orders = profile_dataset(
        Dataset(
            frame=pd.DataFrame(
                {"id": range(40), "customer_id": [5000 + (i % 20) for i in range(40)]}
            ),
            schema=_ORDERS_SCHEMA,
        ),
        salt="s",
    )
    spec = bootstrap_spec({"customers": customers, "orders": orders}, seed=3)
    spec.tables["customers"].shared_keys = ["customer_id"]
    spec.tables["customers"].reserved_key_block = 100
    out = generate_from_spec(spec)
    parent_keys = set(out["customers"].frame["customer_id"])
    assert parent_keys == set(range(100, 120))  # position-derived, source 5000.. gone
    assert set(out["orders"].frame["customer_id"]).issubset(parent_keys)  # FK remapped, RI holds


def test_shared_key_that_is_also_sensitive_is_not_regenerated() -> None:
    # A shared column marked sensitive must keep its deterministic position-derived value: the
    # seal gate must NOT regenerate it (F3). Real source ids overlap the reserved block to bait it.
    customers = profile_dataset(
        Dataset(
            frame=pd.DataFrame(
                {"customer_id": range(100, 120), "email": [f"c{i}@x.com" for i in range(20)]}
            ),
            schema=_CUSTOMERS_SCHEMA,
        ),
        sensitive_columns=["customer_id"],  # shared AND sensitive
        salt="s",
    )
    spec = bootstrap_spec({"customers": customers}, seed=7)
    spec.tables["customers"].shared_keys = ["customer_id"]
    spec.tables["customers"].reserved_key_block = 100
    out = generate_from_spec(spec)
    assert list(out["customers"].frame["customer_id"]) == list(range(100, 120))  # not regenerated


def _spec_with_shared(*, seed: int, source_start: int):
    customers = profile_dataset(
        Dataset(
            frame=pd.DataFrame(
                {
                    "customer_id": range(source_start, source_start + 20),
                    "email": [f"c{i}@x.com" for i in range(20)],
                }
            ),
            schema=_CUSTOMERS_SCHEMA,
        ),
        salt="s",
    )
    spec = bootstrap_spec({"customers": customers}, seed=seed)
    spec.tables["customers"].shared_keys = ["customer_id"]
    spec.tables["customers"].reserved_key_block = 50
    return spec


# --- reserved keyspace validation (fail closed, PDE-10) ---------------------


def test_fixture_key_outside_reserved_block_fails_closed() -> None:
    with pytest.raises(KeyspaceError, match="outside the reserved block"):
        apply_shared_keys(
            {"customers": _customers(10)},
            shared_by_table={"customers": ["customer_id"]},
            reserved_by_table={"customers": 5},
            fixture_keys_by_table={"customers": {"customer_id": [3, 99]}},  # 99 >= 5 -> reject
        )


def test_fixture_key_inside_reserved_block_is_accepted() -> None:
    out = apply_shared_keys(
        {"customers": _customers(10)},
        shared_by_table={"customers": ["customer_id"]},
        reserved_by_table={"customers": 5},
        fixture_keys_by_table={"customers": {"customer_id": [0, 3, 4]}},  # all in [0, 5)
    )
    assert list(out["customers"].frame["customer_id"]) == list(range(5, 15))  # generated at/above 5


def test_shared_column_that_is_a_foreign_key_fails_closed() -> None:
    with pytest.raises(KeyspaceError, match="is a foreign key"):
        apply_shared_keys(
            {"customers": _customers(5), "orders": _orders(10, 5)},
            shared_by_table={"orders": ["customer_id"]},  # customer_id in orders is an FK
            reserved_by_table={"orders": 0},
        )


def test_shared_keys_for_unknown_table_fails_closed() -> None:
    with pytest.raises(KeyspaceError, match="was not generated"):
        apply_shared_keys(
            {"customers": _customers(5)},
            shared_by_table={"ghost": ["id"]},
            reserved_by_table={},
        )


def test_missing_shared_column_fails_closed() -> None:
    with pytest.raises(KeyspaceError, match="is not in table"):
        apply_shared_keys(
            {"customers": _customers(5)},
            shared_by_table={"customers": ["nope"]},
            reserved_by_table={"customers": 0},
        )
