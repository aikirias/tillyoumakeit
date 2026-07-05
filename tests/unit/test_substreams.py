"""PRD 1 Story 2.1: per-table RNG substreams (AD-20)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from tymi.domain.artifacts import Column, Dataset, ForeignKey, LogicalType, Schema
from tymi.profiling.profiler import profile_dataset
from tymi.synth.relational import generate_related
from tymi.synth.substreams import table_substream

_SCHEMA = Schema(columns=(Column("v", LogicalType.INTEGER), Column("w", LogicalType.FLOAT)))

_PARENT_SCHEMA = Schema(
    columns=(Column("id", LogicalType.INTEGER, primary_key=True),),
    primary_key=("id",),
)
_CHILD_SCHEMA = Schema(
    columns=(
        Column("id", LogicalType.INTEGER, primary_key=True),
        Column("parent_id", LogicalType.INTEGER),
    ),
    primary_key=("id",),
    foreign_keys=(ForeignKey(("parent_id",), "parent", ("id",)),),
)


def _profile(name_seed: int = 0):
    rng = np.random.default_rng(name_seed)
    frame = pd.DataFrame({"v": range(50), "w": rng.normal(0, 1, 50)})
    return profile_dataset(Dataset(frame=frame, schema=_SCHEMA), salt="s")


def _parent():
    return profile_dataset(
        Dataset(frame=pd.DataFrame({"id": range(30)}), schema=_PARENT_SCHEMA), salt="s"
    )


def _child():
    return profile_dataset(
        Dataset(
            frame=pd.DataFrame({"id": range(50), "parent_id": [i % 30 for i in range(50)]}),
            schema=_CHILD_SCHEMA,
        ),
        salt="s",
    )


# --- the substream primitive -------------------------------------------------


def test_substream_is_deterministic() -> None:
    a = table_substream(7, "customers").integers(0, 1_000_000, size=20)
    b = table_substream(7, "customers").integers(0, 1_000_000, size=20)
    assert np.array_equal(a, b)  # same (seed, name) -> same stream


def test_distinct_tables_get_independent_streams() -> None:
    a = table_substream(7, "customers").integers(0, 1_000_000, size=20)
    b = table_substream(7, "orders").integers(0, 1_000_000, size=20)
    assert not np.array_equal(a, b)  # distinct names -> independent streams


def test_seed_changes_the_stream() -> None:
    a = table_substream(1, "t").integers(0, 1_000_000, size=20)
    b = table_substream(2, "t").integers(0, 1_000_000, size=20)
    assert not np.array_equal(a, b)


def test_negative_seed_accepted() -> None:
    # seed is masked to 64 bits, so a negative seed is valid and deterministic.
    a = table_substream(-5, "t").integers(0, 1_000_000, size=10)
    b = table_substream(-5, "t").integers(0, 1_000_000, size=10)
    assert np.array_equal(a, b)


# --- the AD-20 property end-to-end through generate_related ------------------


def test_table_output_independent_of_unrelated_table_row_count() -> None:
    # 'beta' has no relationship to 'alpha'; changing alpha's row count must not move beta.
    profiles = {"alpha": _profile(1), "beta": _profile(2)}
    gen_small = generate_related(profiles, rows={"alpha": 30, "beta": 40}, seed=5)
    gen_big = generate_related(profiles, rows={"alpha": 99, "beta": 40}, seed=5)
    pd.testing.assert_frame_equal(gen_small["beta"].frame, gen_big["beta"].frame)


def test_child_fk_edges_stable_when_unrelated_table_changes() -> None:
    # The AD-20 wedge: a FK-bearing child's rows AND FK edges must be byte-identical when an
    # UNRELATED table's row count changes (parent unchanged). This is what keeps the same shared
    # entities' relationships identical across teams.
    profiles = {"parent": _parent(), "child": _child(), "other": _profile(9)}
    small = generate_related(
        profiles, rows={"parent": 30, "child": 50, "other": 20}, seed=5
    )
    big = generate_related(
        profiles, rows={"parent": 30, "child": 50, "other": 500}, seed=5
    )
    # child's whole frame, FK column included, is untouched by 'other' growing 25x
    pd.testing.assert_frame_equal(small["child"].frame, big["child"].frame)
    pd.testing.assert_frame_equal(small["parent"].frame, big["parent"].frame)


def test_generation_order_does_not_change_output() -> None:
    # Reordering the input dict must not change any table's output (order-independence, AD-20).
    a, b = _profile(1), _profile(2)
    forward = generate_related({"alpha": a, "beta": b}, rows={"alpha": 30, "beta": 40}, seed=5)
    reversed_ = generate_related({"beta": b, "alpha": a}, rows={"alpha": 30, "beta": 40}, seed=5)
    for table in ("alpha", "beta"):
        pd.testing.assert_frame_equal(forward[table].frame, reversed_[table].frame)


def test_same_seed_is_reproducible() -> None:
    profiles = {"alpha": _profile(1), "beta": _profile(2)}
    a = generate_related(profiles, rows={"alpha": 30, "beta": 40}, seed=5)
    b = generate_related(profiles, rows={"alpha": 30, "beta": 40}, seed=5)
    for table in ("alpha", "beta"):
        pd.testing.assert_frame_equal(a[table].frame, b[table].frame)
