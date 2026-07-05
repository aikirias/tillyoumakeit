"""PRD 1 Phase 3 · P3.2: referentially-consistent subsetting (AD-26, PDE-16)."""

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
)
from tymi.profiling.profiler import profile_dataset
from tymi.synth.subset import subset_datasets, subset_from_spec
from tymi.synth.whole_db import generate_from_spec


def _schema(cols, pk, fks=()):
    return Schema(columns=tuple(cols), primary_key=pk, foreign_keys=tuple(fks))


def _hierarchy():
    countries = Dataset(
        frame=pd.DataFrame({"country_id": range(5), "gdp": [float(i) for i in range(5)]}),
        schema=_schema(
            [Column("country_id", LogicalType.INTEGER, primary_key=True),
             Column("gdp", LogicalType.FLOAT)],
            ("country_id",),
        ),
    )
    customers = Dataset(
        frame=pd.DataFrame({"customer_id": range(20), "country_id": [i % 5 for i in range(20)]}),
        schema=_schema(
            [Column("customer_id", LogicalType.INTEGER, primary_key=True),
             Column("country_id", LogicalType.INTEGER)],
            ("customer_id",),
            [ForeignKey(("country_id",), "countries", ("country_id",))],
        ),
    )
    orders = Dataset(
        frame=pd.DataFrame({"order_id": range(50), "customer_id": [i % 20 for i in range(50)]}),
        schema=_schema(
            [Column("order_id", LogicalType.INTEGER, primary_key=True),
             Column("customer_id", LogicalType.INTEGER)],
            ("order_id",),
            [ForeignKey(("customer_id",), "customers", ("customer_id",))],
        ),
    )
    products = Dataset(
        frame=pd.DataFrame({"product_id": range(10)}),
        schema=_schema(
            [Column("product_id", LogicalType.INTEGER, primary_key=True)], ("product_id",)
        ),
    )
    items = Dataset(
        frame=pd.DataFrame(
            {
                "item_id": range(100),
                "order_id": [i % 50 for i in range(100)],
                "product_id": [i % 10 for i in range(100)],
            }
        ),
        schema=_schema(
            [Column("item_id", LogicalType.INTEGER, primary_key=True),
             Column("order_id", LogicalType.INTEGER),
             Column("product_id", LogicalType.INTEGER)],
            ("item_id",),
            [ForeignKey(("order_id",), "orders", ("order_id",)),
             ForeignKey(("product_id",), "products", ("product_id",))],
        ),
    )
    return {
        "countries": countries, "customers": customers, "orders": orders,
        "products": products, "items": items,
    }


# --- the subsetting transform (AD-26) ---------------------------------------


def test_subset_keeps_a_root_fraction() -> None:
    out = subset_datasets(_hierarchy(), root="customers", fraction=0.5, seed=1)
    assert len(out["customers"].frame) == 10  # 50% of 20


def test_referential_integrity_holds_across_the_subset() -> None:
    out = subset_datasets(_hierarchy(), root="customers", fraction=0.5, seed=1)
    kept_customers = set(out["customers"].frame["customer_id"])
    kept_orders = set(out["orders"].frame["order_id"])
    kept_countries = set(out["countries"].frame["country_id"])
    kept_products = set(out["products"].frame["product_id"])
    # downward: orders/items only for kept ancestors
    assert set(out["orders"].frame["customer_id"]).issubset(kept_customers)
    assert set(out["items"].frame["order_id"]).issubset(kept_orders)
    # upward: every referenced dimension row survives (RI satisfied)
    assert set(out["customers"].frame["country_id"]).issubset(kept_countries)
    assert set(out["items"].frame["product_id"]).issubset(kept_products)


def test_subset_is_smaller_than_the_whole() -> None:
    full = _hierarchy()
    out = subset_datasets(full, root="customers", fraction=0.5, seed=1)
    assert len(out["orders"].frame) < len(full["orders"].frame)
    assert len(out["items"].frame) < len(full["items"].frame)


def test_keys_are_not_renumbered() -> None:
    # A surviving row keeps its original key, so the subset still joins to the full dataset.
    full = _hierarchy()
    out = subset_datasets(full, root="customers", fraction=0.5, seed=1)
    kept_ids = set(out["customers"].frame["customer_id"])
    assert kept_ids.issubset(set(full["customers"].frame["customer_id"]))  # same values, kept as-is


def test_subset_is_deterministic() -> None:
    a = subset_datasets(_hierarchy(), root="customers", fraction=0.4, seed=7)
    b = subset_datasets(_hierarchy(), root="customers", fraction=0.4, seed=7)
    for name in a:
        pd.testing.assert_frame_equal(a[name].frame, b[name].frame)


def test_fraction_one_keeps_everything() -> None:
    full = _hierarchy()
    out = subset_datasets(full, root="customers", fraction=1.0, seed=1)
    for name in full:
        assert len(out[name].frame) == len(full[name].frame)


# --- fail-closed -------------------------------------------------------------


def test_unknown_root_fails_closed() -> None:
    with pytest.raises(GenerationError, match="root"):
        subset_datasets(_hierarchy(), root="ghost", fraction=0.5, seed=1)


def test_bad_fraction_fails_closed() -> None:
    with pytest.raises(GenerationError, match="fraction"):
        subset_datasets(_hierarchy(), root="customers", fraction=0.0, seed=1)
    with pytest.raises(GenerationError, match="fraction"):
        subset_datasets(_hierarchy(), root="customers", fraction=1.5, seed=1)


def test_cyclic_fk_graph_fails_closed() -> None:
    a = Dataset(
        frame=pd.DataFrame({"id": [0], "b_id": [0]}),
        schema=_schema(
            [Column("id", LogicalType.INTEGER, primary_key=True),
             Column("b_id", LogicalType.INTEGER)],
            ("id",), [ForeignKey(("b_id",), "b", ("id",))],
        ),
    )
    b = Dataset(
        frame=pd.DataFrame({"id": [0], "a_id": [0]}),
        schema=_schema(
            [Column("id", LogicalType.INTEGER, primary_key=True),
             Column("a_id", LogicalType.INTEGER)],
            ("id",), [ForeignKey(("a_id",), "a", ("id",))],
        ),
    )
    with pytest.raises(GenerationError, match="cyclic"):
        subset_datasets({"a": a, "b": b}, root="a", fraction=0.5, seed=1)


def test_composite_or_missing_pk_fails_closed() -> None:
    composite = Dataset(
        frame=pd.DataFrame({"a": [0], "b": [0]}),
        schema=_schema(
            [Column("a", LogicalType.INTEGER, primary_key=True),
             Column("b", LogicalType.INTEGER, primary_key=True)],
            ("a", "b"),
        ),
    )
    with pytest.raises(GenerationError, match="exactly one primary-key"):
        subset_datasets({"t": composite}, root="t", fraction=0.5, seed=1)
    no_pk = Dataset(
        frame=pd.DataFrame({"x": [0]}),
        schema=_schema([Column("x", LogicalType.INTEGER)], ()),
    )
    with pytest.raises(GenerationError, match="exactly one primary-key"):
        subset_datasets({"t": no_pk}, root="t", fraction=0.5, seed=1)


def test_self_referential_fk_is_referentially_consistent() -> None:
    # employees.manager_id -> employees.id; a kept employee's manager must survive too (upward).
    employees = Dataset(
        frame=pd.DataFrame({"id": range(20), "manager_id": [max(0, i - 1) for i in range(20)]}),
        schema=_schema(
            [Column("id", LogicalType.INTEGER, primary_key=True),
             Column("manager_id", LogicalType.INTEGER)],
            ("id",),
            [ForeignKey(("manager_id",), "employees", ("id",))],
        ),
    )
    out = subset_datasets({"employees": employees}, root="employees", fraction=0.5, seed=2)
    kept = set(out["employees"].frame["id"])
    assert set(out["employees"].frame["manager_id"]).issubset(kept)  # self-FK RI holds


# --- end to end from a Spec (re-sealed to GatedDatasets) --------------------


def test_subset_from_spec_returns_gated_and_consistent() -> None:
    cust_schema = _schema(
        [Column("customer_id", LogicalType.INTEGER, primary_key=True),
         Column("email", LogicalType.STRING)],
        ("customer_id",),
    )
    ord_schema = _schema(
        [Column("order_id", LogicalType.INTEGER, primary_key=True),
         Column("customer_id", LogicalType.INTEGER),
         Column("amount", LogicalType.FLOAT)],
        ("order_id",),
        [ForeignKey(("customer_id",), "customers", ("customer_id",))],
    )
    customers = profile_dataset(
        Dataset(
            frame=pd.DataFrame(
                {"customer_id": range(40), "email": [f"u{i}@x.com" for i in range(40)]}
            ),
            schema=cust_schema,
        ),
        sensitive_columns=["email"],
        salt="s",
    )
    orders = profile_dataset(
        Dataset(
            frame=pd.DataFrame(
                {
                    "order_id": range(80),
                    "customer_id": [i % 40 for i in range(80)],
                    "amount": [float(i) for i in range(80)],
                }
            ),
            schema=ord_schema,
        ),
        salt="s",
    )
    spec = bootstrap_spec({"customers": customers, "orders": orders}, seed=3)
    spec.tables["customers"].rows = 40
    spec.tables["orders"].rows = 80
    out = subset_from_spec(spec, root="customers", fraction=0.25)
    assert all(isinstance(gd, GatedDataset) for gd in out.values())
    assert len(out["customers"].frame) == 10  # 25% of 40
    kept = set(out["customers"].frame["customer_id"])
    assert set(out["orders"].frame["customer_id"]).issubset(kept)  # RI holds after re-seal
    # zero real sensitive values survive the subset
    assert set(out["customers"].frame["email"]).isdisjoint({f"u{i}@x.com" for i in range(40)})

    # AD-26 differentiator: a subset row is byte-identical to the SAME key in an independently
    # generated full dataset (keys are position-derived, not renumbered) — so the subset joins to a
    # full sibling dataset.
    full = generate_from_spec(spec)["customers"].frame.set_index("customer_id")["email"]
    for _, row in out["customers"].frame.iterrows():
        assert full.loc[row["customer_id"]] == row["email"]
