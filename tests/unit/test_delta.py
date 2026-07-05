"""PRD 1 Phase 3 · P3.3: incremental / delta refresh (AD-27, PDE-17)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from tymi.config.spec import CrossCorrelation, bootstrap_spec
from tymi.domain.artifacts import Column, Dataset, ForeignKey, GatedDataset, LogicalType, Schema
from tymi.profiling.profile_io import profile_to_dict
from tymi.profiling.profiler import profile_dataset
from tymi.synth.delta import delta_refresh
from tymi.synth.whole_db import generate_from_spec

_CUST = Schema(
    columns=(
        Column("customer_id", LogicalType.INTEGER, primary_key=True),
        Column("tier", LogicalType.FLOAT),
    ),
    primary_key=("customer_id",),
)
_ORD = Schema(
    columns=(
        Column("order_id", LogicalType.INTEGER, primary_key=True),
        Column("customer_id", LogicalType.INTEGER),
        Column("amount", LogicalType.FLOAT),
    ),
    primary_key=("order_id",),
    foreign_keys=(ForeignKey(("customer_id",), "customers", ("customer_id",)),),
)
_ITEM = Schema(
    columns=(
        Column("item_id", LogicalType.INTEGER, primary_key=True),
        Column("order_id", LogicalType.INTEGER),
    ),
    primary_key=("item_id",),
    foreign_keys=(ForeignKey(("order_id",), "orders", ("order_id",)),),
)


def _cust_profile(shift=0.0):
    rng = np.random.default_rng(0)
    return profile_dataset(
        Dataset(
            frame=pd.DataFrame({"customer_id": range(30), "tier": rng.normal(shift, 1, 30)}),
            schema=_CUST,
        ),
        salt="s",
    )


def _base_spec():
    rng = np.random.default_rng(1)
    orders = profile_dataset(
        Dataset(
            frame=pd.DataFrame(
                {
                    "order_id": range(60),
                    "customer_id": [i % 30 for i in range(60)],
                    "amount": rng.normal(0, 1, 60),
                }
            ),
            schema=_ORD,
        ),
        salt="s",
    )
    items = profile_dataset(
        Dataset(
            frame=pd.DataFrame({"item_id": range(100), "order_id": [i % 60 for i in range(100)]}),
            schema=_ITEM,
        ),
        salt="s",
    )
    spec = bootstrap_spec(
        {"customers": _cust_profile(), "orders": orders, "items": items}, seed=5
    )
    spec.tables["customers"].rows = 30
    spec.tables["orders"].rows = 60
    spec.tables["items"].rows = 100
    return spec


def test_no_change_reuses_everything() -> None:
    prev = _base_spec()
    new = prev.model_copy(deep=True)
    result = delta_refresh(prev, new)
    assert result.regenerated == {}
    assert set(result.reused) == {"customers", "orders", "items"}


def test_profile_only_change_regenerates_just_that_table() -> None:
    prev = _base_spec()
    new = prev.model_copy(deep=True)
    new.tables["customers"].profile = profile_to_dict(_cust_profile(shift=9.0))  # new data, same n
    result = delta_refresh(prev, new)
    assert set(result.regenerated) == {"customers"}  # only customers dirty
    assert set(result.reused) == {"orders", "items"}  # keys unchanged -> children reused
    # the reused tables are byte-identical to a full generation of the new spec
    full = generate_from_spec(new)
    for name in result.reused:
        pd.testing.assert_frame_equal(full[name].frame, generate_from_spec(prev)[name].frame)


def test_row_count_change_propagates_exactly_one_hop() -> None:
    prev = _base_spec()
    new = prev.model_copy(deep=True)
    new.tables["customers"].rows = 40  # key-affecting: changes customers' key range
    result = delta_refresh(prev, new)
    # customers (direct) + orders (direct child of a key-affecting parent) dirty; items reused
    assert set(result.regenerated) == {"customers", "orders"}
    assert set(result.reused) == {"items"}


def test_global_seed_change_regenerates_all() -> None:
    prev = _base_spec()
    new = prev.model_copy(deep=True)
    new.seed = 99
    result = delta_refresh(prev, new)
    assert set(result.regenerated) == {"customers", "orders", "items"}
    assert result.reused == ()


def test_new_and_dropped_tables() -> None:
    prev = _base_spec()
    new = prev.model_copy(deep=True)
    del new.tables["items"]  # dropped
    new.tables["reviews"] = prev.tables["items"].model_copy(deep=True)  # new (reuses a profile)
    result = delta_refresh(prev, new)
    assert "reviews" in result.regenerated  # a new table is dirty
    assert result.dropped == ("items",)


def test_chunk_rows_change_regenerates_all() -> None:
    prev = _base_spec()
    new = prev.model_copy(deep=True)
    new.chunk_rows = prev.chunk_rows + 1
    assert set(delta_refresh(prev, new).regenerated) == {"customers", "orders", "items"}


def test_render_reports_regenerated_reused_and_fingerprint() -> None:
    prev = _base_spec()
    new = prev.model_copy(deep=True)
    new.tables["customers"].rows = 40
    text = delta_refresh(prev, new).render()
    assert "regenerated" in text and "reused" in text
    assert "Consistency-unit fingerprint:" in text


def test_cross_correlated_child_is_dirty_when_its_parent_profile_changes() -> None:
    # A profile-only change to a parent is NOT key-affecting, but a child that cross-correlates
    # against the parent's DATA must still be regenerated (else it is served stale).
    prev = _base_spec()
    prev.tables["orders"].cross_correlations = [
        CrossCorrelation(column="amount", parent_table="customers", parent_column="tier", rho=0.8)
    ]
    new = prev.model_copy(deep=True)
    new.tables["customers"].profile = profile_to_dict(_cust_profile(shift=9.0))  # data change only
    result = delta_refresh(prev, new)
    assert {"customers", "orders"}.issubset(set(result.regenerated))  # child not left stale
    assert "orders" not in result.reused
    # items (no correlation, keys unchanged) is still safely reused
    assert "items" in result.reused


def test_gated_and_ri_holds_between_regenerated_and_reused() -> None:
    prev = _base_spec()
    new = prev.model_copy(deep=True)
    new.tables["customers"].profile = profile_to_dict(_cust_profile(shift=5.0))
    result = delta_refresh(prev, new)
    assert all(isinstance(gd, GatedDataset) for gd in result.regenerated.values())
    # the regenerated customers' keys still line up with orders' (reused) FK values
    full = generate_from_spec(new)
    regenerated_keys = set(result.regenerated["customers"].frame["customer_id"])
    reused_order_fks = set(full["orders"].frame["customer_id"])
    assert reused_order_fks.issubset(regenerated_keys)  # RI preserved across the delta
