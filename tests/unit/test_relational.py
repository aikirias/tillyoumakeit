"""AC-1..AC-3/AC-6 (2.3): multi-table referential integrity (no DB)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tymi.core.errors import GenerationError
from tymi.domain.artifacts import (
    Column,
    Dataset,
    ForeignKey,
    LogicalType,
    Profile,
    Schema,
)
from tymi.profiling.profiler import profile_dataset
from tymi.synth.relational import _dedupe_object, generate_related


def _profile(frame: pd.DataFrame, schema: Schema) -> Profile:
    return profile_dataset(Dataset(frame=frame, schema=schema))


def _users() -> Profile:
    frame = pd.DataFrame(
        {"id": range(40), "email": [f"u{i}@corp.com" for i in range(40)]}
    )
    schema = Schema(
        columns=(Column("id", LogicalType.INTEGER), Column("email", LogicalType.STRING)),
        primary_key=("id",),
        unique_constraints=(("email",),),
    )
    return _profile(frame, schema)


def _orders() -> Profile:
    frame = pd.DataFrame(
        {
            "id": range(120),
            "user_id": [i % 40 for i in range(120)],
            "amount": np.linspace(1, 500, 120),
        }
    )
    schema = Schema(
        columns=(
            Column("id", LogicalType.INTEGER),
            Column("user_id", LogicalType.INTEGER),
            Column("amount", LogicalType.FLOAT),
        ),
        primary_key=("id",),
        foreign_keys=(ForeignKey(("user_id",), "users", ("id",)),),
    )
    return _profile(frame, schema)


def test_referential_integrity_and_unique_pks() -> None:
    out = generate_related(
        {"orders": _orders(), "users": _users()},  # deliberately child-first input
        rows={"users": 40, "orders": 300},
        seed=0,
    )
    users, orders = out["users"].frame, out["orders"].frame
    assert users["id"].is_unique  # AC-2
    assert orders["id"].is_unique
    # AC-1: every FK points at a real parent PK
    assert set(orders["user_id"]).issubset(set(users["id"]))
    assert len(orders) == 300 and len(users) == 40


def test_unique_constraint_holds() -> None:
    out = generate_related({"users": _users()}, rows={"users": 40}, seed=0)
    assert out["users"].frame["email"].is_unique  # AC-3


def test_schema_preserved() -> None:
    users = _users()
    out = generate_related({"users": users}, rows={"users": 10}, seed=0)
    assert out["users"].schema == users.schema  # AC-6 / AD-10


def test_cycle_raises() -> None:
    a = _profile(
        pd.DataFrame({"id": range(5), "b_id": range(5)}),
        Schema(
            columns=(Column("id", LogicalType.INTEGER), Column("b_id", LogicalType.INTEGER)),
            primary_key=("id",),
            foreign_keys=(ForeignKey(("b_id",), "b", ("id",)),),
        ),
    )
    b = _profile(
        pd.DataFrame({"id": range(5), "a_id": range(5)}),
        Schema(
            columns=(Column("id", LogicalType.INTEGER), Column("a_id", LogicalType.INTEGER)),
            primary_key=("id",),
            foreign_keys=(ForeignKey(("a_id",), "a", ("id",)),),
        ),
    )
    with pytest.raises(GenerationError, match="cyclic"):
        generate_related({"a": a, "b": b}, rows=5, seed=0)


def test_self_referential_fk() -> None:
    # employees.manager_id -> employees.id
    frame = pd.DataFrame({"id": range(30), "manager_id": [0] * 30})
    schema = Schema(
        columns=(Column("id", LogicalType.INTEGER), Column("manager_id", LogicalType.INTEGER)),
        primary_key=("id",),
        foreign_keys=(ForeignKey(("manager_id",), "employees", ("id",)),),
    )
    out = generate_related({"employees": _profile(frame, schema)}, rows=50, seed=0)
    emp = out["employees"].frame
    assert emp["id"].is_unique
    assert set(emp["manager_id"]).issubset(set(emp["id"]))  # every manager is an employee


def test_composite_foreign_key_consistency() -> None:
    parent = _profile(
        pd.DataFrame({"a": [i // 2 for i in range(20)], "b": range(20), "v": range(20)}),
        Schema(
            columns=(
                Column("a", LogicalType.INTEGER),
                Column("b", LogicalType.INTEGER),
                Column("v", LogicalType.INTEGER),
            ),
            primary_key=("a", "b"),
        ),
    )
    child = _profile(
        pd.DataFrame({"id": range(60), "pa": [0] * 60, "pb": [0] * 60}),
        Schema(
            columns=(
                Column("id", LogicalType.INTEGER),
                Column("pa", LogicalType.INTEGER),
                Column("pb", LogicalType.INTEGER),
            ),
            primary_key=("id",),
            foreign_keys=(ForeignKey(("pa", "pb"), "parent", ("a", "b")),),
        ),
    )
    out = generate_related({"parent": parent, "child": child}, rows=60, seed=0)
    p, c = out["parent"].frame, out["child"].frame
    parent_pairs = set(zip(p["a"], p["b"], strict=False))
    child_pairs = set(zip(c["pa"], c["pb"], strict=False))
    assert child_pairs.issubset(parent_pairs)  # composite FK stays a valid parent pair


def test_missing_row_count_raises() -> None:
    with pytest.raises(GenerationError, match="row count"):
        generate_related({"users": _users()}, rows={"orders": 10}, seed=0)


def test_deterministic_same_seed() -> None:
    args = {"orders": _orders(), "users": _users()}
    a = generate_related(args, rows={"users": 40, "orders": 100}, seed=7)
    b = generate_related(args, rows={"users": 40, "orders": 100}, seed=7)
    for table in a:
        pd.testing.assert_frame_equal(a[table].frame, b[table].frame)


def _students() -> Profile:
    return _profile(
        pd.DataFrame({"id": range(10), "name": [f"s{i}" for i in range(10)]}),
        Schema(
            columns=(Column("id", LogicalType.INTEGER), Column("name", LogicalType.STRING)),
            primary_key=("id",),
        ),
    )


def _courses() -> Profile:
    return _profile(
        pd.DataFrame({"id": range(6), "title": [f"c{i}" for i in range(6)]}),
        Schema(
            columns=(Column("id", LogicalType.INTEGER), Column("title", LogicalType.STRING)),
            primary_key=("id",),
        ),
    )


def _enrollments() -> Profile:
    # pure junction table: PK = (student_id, course_id), both FKs
    return _profile(
        pd.DataFrame({"student_id": [0] * 20, "course_id": [0] * 20}),
        Schema(
            columns=(
                Column("student_id", LogicalType.INTEGER),
                Column("course_id", LogicalType.INTEGER),
            ),
            primary_key=("student_id", "course_id"),
            foreign_keys=(
                ForeignKey(("student_id",), "students", ("id",)),
                ForeignKey(("course_id",), "courses", ("id",)),
            ),
        ),
    )


def test_junction_table_unique_and_valid() -> None:
    out = generate_related(
        {"enrollments": _enrollments(), "students": _students(), "courses": _courses()},
        rows={"students": 10, "courses": 6, "enrollments": 40},
        seed=0,
    )
    enr = out["enrollments"].frame
    students, courses = out["students"].frame, out["courses"].frame
    # AC-2: the composite PK (which is entirely FK-bound) is unique...
    assert not enr.duplicated(subset=["student_id", "course_id"]).any()
    # ...AC-1: and every FK component points at a real parent.
    assert set(enr["student_id"]).issubset(set(students["id"]))
    assert set(enr["course_id"]).issubset(set(courses["id"]))


def test_junction_capacity_exceeded_raises() -> None:
    # 10 students x 6 courses = 60 combos; asking for 100 unique rows is impossible.
    with pytest.raises(GenerationError, match="combinations"):
        generate_related(
            {"enrollments": _enrollments(), "students": _students(), "courses": _courses()},
            rows={"students": 10, "courses": 6, "enrollments": 100},
            seed=0,
        )


def test_pk_that_is_also_fk_stays_unique() -> None:
    # 1:1 identifying relationship: profile.user_id is BOTH PK and FK -> users.id
    users = _users()
    profile = _profile(
        pd.DataFrame({"user_id": range(40), "bio": [f"b{i}" for i in range(40)]}),
        Schema(
            columns=(Column("user_id", LogicalType.INTEGER), Column("bio", LogicalType.STRING)),
            primary_key=("user_id",),
            foreign_keys=(ForeignKey(("user_id",), "users", ("id",)),),
        ),
    )
    out = generate_related(
        {"profiles": profile, "users": users},
        rows={"users": 40, "profiles": 30},
        seed=0,
    )
    prof, u = out["profiles"].frame, out["users"].frame
    assert prof["user_id"].is_unique  # PK-that-is-also-FK stays unique
    assert set(prof["user_id"]).issubset(set(u["id"]))  # and valid


def test_surrogate_pk_with_fk_column() -> None:
    # PK = (id surrogate) with a separate FK column user_id -> users.id
    out = generate_related(
        {"orders": _orders(), "users": _users()},
        rows={"users": 40, "orders": 200},
        seed=0,
    )
    orders, users = out["orders"].frame, out["users"].frame
    assert orders["id"].is_unique
    assert set(orders["user_id"]).issubset(set(users["id"]))


def test_fk_to_non_pk_unique_column() -> None:
    parent = _profile(
        pd.DataFrame({"id": range(20), "code": [f"K{i}" for i in range(20)]}),
        Schema(
            columns=(Column("id", LogicalType.INTEGER), Column("code", LogicalType.STRING)),
            primary_key=("id",),
            unique_constraints=(("code",),),
        ),
    )
    child = _profile(
        pd.DataFrame({"id": range(50), "parent_code": ["K0"] * 50}),
        Schema(
            columns=(
                Column("id", LogicalType.INTEGER),
                Column("parent_code", LogicalType.STRING),
            ),
            primary_key=("id",),
            foreign_keys=(ForeignKey(("parent_code",), "parent", ("code",)),),
        ),
    )
    out = generate_related(
        {"parent": parent, "child": child}, rows={"parent": 20, "child": 80}, seed=0
    )
    # FK to a non-PK unique column must still resolve to a real parent value
    assert set(out["child"].frame["parent_code"]).issubset(set(out["parent"].frame["code"]))


def test_numeric_unique_constraint_stays_numeric_and_unique() -> None:
    # a low-range integer unique column will collide out of the marginal sampler;
    # enforcement must keep it unique AND numeric (not stringified).
    frame = pd.DataFrame({"id": range(50), "slot": [i % 5 for i in range(50)]})
    schema = Schema(
        columns=(Column("id", LogicalType.INTEGER), Column("slot", LogicalType.INTEGER)),
        primary_key=("id",),
        unique_constraints=(("slot",),),
    )
    out = generate_related({"t": _profile(frame, schema)}, rows={"t": 50}, seed=0)
    slot = out["t"].frame["slot"]
    assert slot.is_unique
    assert pd.api.types.is_numeric_dtype(slot.dtype)  # not coerced to object strings


def test_fk_column_keeps_integer_dtype() -> None:
    out = generate_related(
        {"orders": _orders(), "users": _users()},
        rows={"users": 40, "orders": 100},
        seed=0,
    )
    # FK dtype should follow the parent integer PK, not drift to object
    assert pd.api.types.is_integer_dtype(out["orders"].frame["user_id"].dtype)


def test_junction_capacity_counts_distinct_values() -> None:
    # a junction whose PK column references a NON-unique parent column: capacity is
    # counted in distinct-value space, so an over-request raises instead of silently
    # shipping duplicate PKs.
    grp_parent = _profile(
        pd.DataFrame({"id": range(10), "grp": [i % 2 for i in range(10)]}),
        Schema(
            columns=(Column("id", LogicalType.INTEGER), Column("grp", LogicalType.INTEGER)),
            primary_key=("id",),
        ),
    )
    junction = _profile(
        pd.DataFrame({"g": [0] * 30, "c": [0] * 30}),
        Schema(
            columns=(Column("g", LogicalType.INTEGER), Column("c", LogicalType.INTEGER)),
            primary_key=("g", "c"),
            foreign_keys=(
                ForeignKey(("g",), "gp", ("grp",)),  # references a NON-unique column
                ForeignKey(("c",), "courses", ("id",)),
            ),
        ),
    )
    # grp has 2 distinct x courses 6 distinct = 12 combos; 30 rows is impossible
    with pytest.raises(GenerationError, match="distinct parent-key combinations"):
        generate_related(
            {"j": junction, "gp": grp_parent, "courses": _courses()},
            rows={"gp": 10, "courses": 6, "j": 30},
            seed=0,
        )


def test_dedupe_object_never_collides() -> None:
    # the suffix must not recreate an already-present value
    out = _dedupe_object(pd.Series(["a", "a", "a-1", "a"]))
    assert out.is_unique
    assert out.isna().sum() == 0
