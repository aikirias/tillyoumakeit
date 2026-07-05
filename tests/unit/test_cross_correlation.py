"""PRD 1 Phase 3 · P3.1: cross-table single-hop correlation (AD-25, PDE-6)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from scipy.stats import spearmanr

from tymi.config.consistency import consistency_fingerprint
from tymi.config.spec import CrossCorrelation, bootstrap_spec
from tymi.core.errors import GenerationError
from tymi.core.rng import make_rng
from tymi.domain.artifacts import Column, Dataset, ForeignKey, LogicalType, Schema
from tymi.profiling.profiler import profile_dataset
from tymi.synth.cross_correlation import apply_cross_correlations, induce_rank_correlation
from tymi.synth.whole_db import generate_from_spec

_CUSTOMERS = Schema(
    columns=(
        Column("customer_id", LogicalType.INTEGER, primary_key=True),
        Column("tier", LogicalType.FLOAT),
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


# --- the primitive -----------------------------------------------------------


def test_induce_rank_correlation_preserves_marginal_and_hits_rho() -> None:
    rng = make_rng(0)
    target = np.arange(100.0)
    reference = rng.normal(0, 1, 100)
    out = induce_rank_correlation(target, reference, 0.8, rng)
    assert sorted(out) == sorted(target)  # marginal preserved (a permutation)
    rho, _ = spearmanr(out, reference)
    assert rho > 0.6  # strong positive rank correlation induced


def test_induce_negative_and_zero_rho() -> None:
    rng = make_rng(1)
    target = np.arange(200.0)
    reference = rng.normal(0, 1, 200)
    neg, _ = spearmanr(induce_rank_correlation(target, reference, -0.8, rng), reference)
    assert neg < -0.6
    zero, _ = spearmanr(induce_rank_correlation(target, reference, 0.0, rng), reference)
    assert abs(zero) < 0.25


def test_induce_is_deterministic_and_handles_tiny_input() -> None:
    a = induce_rank_correlation(np.arange(50.0), np.arange(50.0)[::-1], 0.7, make_rng(3))
    b = induce_rank_correlation(np.arange(50.0), np.arange(50.0)[::-1], 0.7, make_rng(3))
    assert np.array_equal(a, b)
    tiny = induce_rank_correlation(np.array([9.0]), np.array([1.0]), 0.5, make_rng(0))
    assert np.array_equal(tiny, [9.0])  # n<2 returns unchanged


# --- applied over a whole DB (AD-25) ----------------------------------------


def _spec(rho=0.85):
    rng = make_rng(0)
    customers = profile_dataset(
        Dataset(
            frame=pd.DataFrame({"customer_id": range(60), "tier": rng.normal(0, 1, 60)}),
            schema=_CUSTOMERS,
        ),
        salt="s",
    )
    orders = profile_dataset(
        Dataset(
            frame=pd.DataFrame(
                {
                    "order_id": range(200),
                    "customer_id": [i % 60 for i in range(200)],
                    "amount": rng.normal(0, 1, 200),
                }
            ),
            schema=_ORDERS,
        ),
        salt="s",
    )
    spec = bootstrap_spec({"customers": customers, "orders": orders}, seed=5)
    spec.tables["customers"].rows = 60
    spec.tables["orders"].rows = 200
    spec.tables["orders"].cross_correlations = [
        CrossCorrelation(column="amount", parent_table="customers", parent_column="tier", rho=rho)
    ]
    return spec


def _order_vs_parent_tier(out):
    orders = out["orders"].frame
    customers = out["customers"].frame.set_index("customer_id")["tier"]
    parent_tier = customers.reindex(orders["customer_id"]).to_numpy()
    rho, _ = spearmanr(orders["amount"].to_numpy(), parent_tier)
    return rho


def test_cross_correlation_is_induced_across_the_fk() -> None:
    with_corr = _order_vs_parent_tier(generate_from_spec(_spec(rho=0.85)))
    assert with_corr > 0.5  # order amount now tracks the referenced customer's tier
    baseline = _order_vs_parent_tier(generate_from_spec(_spec(rho=0.0)))
    assert abs(baseline) < 0.3  # rho=0 leaves them ~independent


def test_cross_correlation_preserves_the_child_marginal() -> None:
    plain = generate_from_spec(_spec(rho=0.0))["orders"].frame["amount"]
    correlated = generate_from_spec(_spec(rho=0.85))["orders"].frame["amount"]
    # same multiset of amounts — only the row assignment changed
    assert sorted(correlated.round(9)) == sorted(plain.round(9))


def test_cross_correlation_is_deterministic() -> None:
    a = generate_from_spec(_spec())["orders"].frame
    b = generate_from_spec(_spec())["orders"].frame
    pd.testing.assert_frame_equal(a, b)


def test_no_declared_correlation_is_a_no_op() -> None:
    datasets = {"customers": Dataset(frame=pd.DataFrame({"customer_id": [0]}), schema=_CUSTOMERS)}
    out = apply_cross_correlations(datasets, bootstrap_spec({}), rng=make_rng(0))
    assert out is datasets  # short-circuits, no copy


# --- fail-closed validation --------------------------------------------------


def _apply_bad(cc):
    spec = _spec()
    spec.tables["orders"].cross_correlations = [cc]
    return generate_from_spec(spec)


def test_missing_parent_column_fails_closed() -> None:
    with pytest.raises(GenerationError, match="parent column"):
        _apply_bad(
            CrossCorrelation(
                column="amount", parent_table="customers", parent_column="nope", rho=0.5
            )
        )


def test_correlating_a_key_column_fails_closed() -> None:
    with pytest.raises(GenerationError, match="non-key data column"):
        _apply_bad(
            CrossCorrelation(
                column="customer_id", parent_table="customers", parent_column="tier", rho=0.5
            )
        )


def test_self_correlation_fails_closed() -> None:
    with pytest.raises(GenerationError, match="self-referential"):
        _apply_bad(
            CrossCorrelation(
                column="amount", parent_table="orders", parent_column="amount", rho=0.5
            )
        )


def test_no_direct_fk_fails_closed() -> None:
    # correlate customers.tier against orders (customers has no FK to orders) -> fail closed.
    spec = _spec()
    spec.tables["customers"].cross_correlations = [
        CrossCorrelation(column="tier", parent_table="orders", parent_column="amount", rho=0.5)
    ]
    with pytest.raises(GenerationError, match="direct foreign key"):
        generate_from_spec(spec)


def test_non_numeric_column_fails_closed() -> None:
    schema = Schema(
        columns=(
            Column("customer_id", LogicalType.INTEGER, primary_key=True),
            Column("name", LogicalType.STRING),
        ),
        primary_key=("customer_id",),
    )
    child_schema = Schema(
        columns=(
            Column("order_id", LogicalType.INTEGER, primary_key=True),
            Column("customer_id", LogicalType.INTEGER),
            Column("note", LogicalType.STRING),
        ),
        primary_key=("order_id",),
        foreign_keys=(ForeignKey(("customer_id",), "customers", ("customer_id",)),),
    )
    customers = profile_dataset(
        Dataset(
            frame=pd.DataFrame({"customer_id": range(10), "name": [f"n{i}" for i in range(10)]}),
            schema=schema,
        ),
        salt="s",
    )
    orders = profile_dataset(
        Dataset(
            frame=pd.DataFrame(
                {
                    "order_id": range(10),
                    "customer_id": range(10),
                    "note": [f"x{i}" for i in range(10)],
                }
            ),
            schema=child_schema,
        ),
        salt="s",
    )
    spec = bootstrap_spec({"customers": customers, "orders": orders}, seed=1)
    spec.tables["orders"].rows = 10
    spec.tables["customers"].rows = 10
    spec.tables["orders"].cross_correlations = [
        CrossCorrelation(column="note", parent_table="customers", parent_column="name", rho=0.5)
    ]
    with pytest.raises(GenerationError, match="must be numeric"):
        generate_from_spec(spec)


def test_multi_hop_fails_closed() -> None:
    # a grandparent (2 hops away) has no DIRECT FK from the child -> fail closed (single-hop only).
    countries = Schema(
        columns=(
            Column("country_id", LogicalType.INTEGER, primary_key=True),
            Column("gdp", LogicalType.FLOAT),
        ),
        primary_key=("country_id",),
    )
    customers = Schema(
        columns=(
            Column("customer_id", LogicalType.INTEGER, primary_key=True),
            Column("country_id", LogicalType.INTEGER),
        ),
        primary_key=("customer_id",),
        foreign_keys=(ForeignKey(("country_id",), "countries", ("country_id",)),),
    )
    c_prof = profile_dataset(
        Dataset(
            frame=pd.DataFrame({"country_id": range(5), "gdp": [float(i) for i in range(5)]}),
            schema=countries,
        ),
        salt="s",
    )
    cust_prof = profile_dataset(
        Dataset(
            frame=pd.DataFrame(
                {"customer_id": range(20), "country_id": [i % 5 for i in range(20)]}
            ),
            schema=customers,
        ),
        salt="s",
    )
    orders = profile_dataset(
        Dataset(
            frame=pd.DataFrame(
                {
                    "order_id": range(30),
                    "customer_id": [i % 20 for i in range(30)],
                    "amount": [float(i) for i in range(30)],
                }
            ),
            schema=_ORDERS,
        ),
        salt="s",
    )
    spec = bootstrap_spec(
        {"countries": c_prof, "customers": cust_prof, "orders": orders}, seed=1
    )
    for t, n in (("countries", 5), ("customers", 20), ("orders", 30)):
        spec.tables[t].rows = n
    # orders → customers → countries; correlate orders.amount against countries.gdp (2 hops).
    spec.tables["orders"].cross_correlations = [
        CrossCorrelation(column="amount", parent_table="countries", parent_column="gdp", rho=0.5)
    ]
    with pytest.raises(GenerationError, match="direct foreign key"):
        generate_from_spec(spec)


def test_integer_child_column_correlation_roundtrips_dtype() -> None:
    child_schema = Schema(
        columns=(
            Column("order_id", LogicalType.INTEGER, primary_key=True),
            Column("customer_id", LogicalType.INTEGER),
            Column("quantity", LogicalType.INTEGER),
        ),
        primary_key=("order_id",),
        foreign_keys=(ForeignKey(("customer_id",), "customers", ("customer_id",)),),
    )
    rng = make_rng(0)
    customers = profile_dataset(
        Dataset(
            frame=pd.DataFrame({"customer_id": range(40), "tier": rng.normal(0, 1, 40)}),
            schema=_CUSTOMERS,
        ),
        salt="s",
    )
    orders = profile_dataset(
        Dataset(
            frame=pd.DataFrame(
                {
                    "order_id": range(120),
                    "customer_id": [i % 40 for i in range(120)],
                    "quantity": rng.integers(1, 50, 120),
                }
            ),
            schema=child_schema,
        ),
        salt="s",
    )
    spec = bootstrap_spec({"customers": customers, "orders": orders}, seed=2)
    spec.tables["customers"].rows = 40
    spec.tables["orders"].rows = 120
    spec.tables["orders"].cross_correlations = [
        CrossCorrelation(
            column="quantity", parent_table="customers", parent_column="tier", rho=0.8
        )
    ]
    out = generate_from_spec(spec)  # must NOT crash on the Int64 write-back
    quantity = out["orders"].frame["quantity"]
    assert str(quantity.dtype) in {"Int64", "int64"}  # integer dtype preserved
    customers_tier = out["customers"].frame.set_index("customer_id")["tier"]
    parent = customers_tier.reindex(out["orders"].frame["customer_id"]).to_numpy()
    rho, _ = spearmanr(quantity.astype("float64").to_numpy(), parent)
    assert rho > 0.4  # correlation induced on the integer column


def test_cross_correlation_declaration_changes_fingerprint() -> None:
    deps = {"tymi": "1", "numpy": "1", "pandas": "1", "faker": "1"}
    plain = _spec(rho=0.0)
    plain.tables["orders"].cross_correlations = []  # remove the declaration entirely
    declared = _spec(rho=0.85)
    assert consistency_fingerprint(plain, deps=deps) != consistency_fingerprint(declared, deps=deps)
