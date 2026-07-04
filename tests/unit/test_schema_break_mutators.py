"""Story 3.4: schema and constraint breakage mutators."""

from __future__ import annotations

import pandas as pd
import pytest

from tymi.chaos.engine import apply_chaos, resolve_mutators
from tymi.chaos.mutators.schema_break import (
    ChangedTypeMutator,
    DuplicateKeysMutator,
    ExtraFieldMutator,
    MissingFieldMutator,
    OrphanFkMutator,
    RenamedColumnMutator,
)
from tymi.core.errors import ChaosError
from tymi.core.plugins import load_mutators
from tymi.core.rng import make_rng
from tymi.domain.artifacts import Column, Dataset, ForeignKey, LogicalType, Schema
from tymi.ports import Mutator

_MUTATORS = {
    "missing_field": MissingFieldMutator,
    "extra_field": ExtraFieldMutator,
    "renamed_column": RenamedColumnMutator,
    "changed_type": ChangedTypeMutator,
    "duplicate_keys": DuplicateKeysMutator,
    "orphan_fk": OrphanFkMutator,
}


def _dataset(n: int = 20) -> Dataset:
    frame = pd.DataFrame(
        {
            "id": pd.array(range(n), dtype="Int64"),
            "parent_id": pd.array(range(n), dtype="Int64"),
            "name": [f"n{i}" for i in range(n)],
        }
    )
    schema = Schema(
        columns=(
            Column("id", LogicalType.INTEGER, primary_key=True),
            Column("parent_id", LogicalType.INTEGER),
            Column("name", LogicalType.STRING),
        ),
        primary_key=("id",),
        foreign_keys=(
            ForeignKey(columns=("parent_id",), referred_table="p", referred_columns=("id",)),
        ),
    )
    return Dataset(frame=frame, schema=schema)


# --- registration + materialization + consistency ---------------------------


@pytest.mark.parametrize("name", list(_MUTATORS))
def test_registered_and_satisfies_port(name: str) -> None:
    assert load_mutators().get(name) is _MUTATORS[name]
    assert isinstance(_MUTATORS[name](), Mutator)


@pytest.mark.parametrize("name", list(_MUTATORS))
def test_breakage_materializes_and_schema_frame_stay_consistent(name: str) -> None:
    out, manifest = apply_chaos(_dataset(), resolve_mutators([name]), rng=make_rng(1))
    assert manifest.entries, f"{name} produced no fault"
    # AD-10: the returned artifact stays internally consistent
    assert list(out.frame.columns) == out.schema.names()


@pytest.mark.parametrize("name", list(_MUTATORS))
def test_deterministic(name: str) -> None:
    a_ds, a_man = apply_chaos(_dataset(), resolve_mutators([name]), rng=make_rng(7))
    b_ds, b_man = apply_chaos(_dataset(), resolve_mutators([name]), rng=make_rng(7))
    assert a_man.entries == b_man.entries
    pd.testing.assert_frame_equal(a_ds.frame, b_ds.frame)


# --- specific breakage semantics --------------------------------------------


def test_missing_field_drops_from_frame_schema_and_keys() -> None:
    out, _ = MissingFieldMutator(columns=["id"]).apply(_dataset(), rng=make_rng(1))
    assert "id" not in out.frame.columns and "id" not in out.schema.names()
    assert out.schema.primary_key == ()  # PK referencing the dropped column is cleaned


def test_extra_field_adds_column_and_rejects_existing() -> None:
    out, _ = ExtraFieldMutator().apply(_dataset(), rng=make_rng(1))
    assert "chaos_extra" in out.frame.columns and "chaos_extra" in out.schema.names()
    with pytest.raises(ChaosError, match="already exists"):
        ExtraFieldMutator(field_name="id").apply(_dataset(), rng=make_rng(1))


def test_renamed_column_updates_frame_schema_and_pk() -> None:
    out, _ = RenamedColumnMutator(columns=["id"]).apply(_dataset(), rng=make_rng(1))
    assert "id__renamed" in out.frame.columns and "id" not in out.frame.columns
    assert out.schema.primary_key == ("id__renamed",)  # PK reference follows the rename


def test_changed_type_flips_schema_type_only() -> None:
    ds = _dataset()
    out, manifest = ChangedTypeMutator(columns=["id"]).apply(ds, rng=make_rng(1))
    (id_col,) = [c for c in out.schema.columns if c.name == "id"]
    assert id_col.logical_type == LogicalType.STRING  # numeric -> string
    pd.testing.assert_series_equal(out.frame["id"], ds.frame["id"])  # frame data unchanged
    assert manifest.entries[0]["from"] == "integer" and manifest.entries[0]["to"] == "string"


def test_duplicate_keys_violates_uniqueness() -> None:
    out, _ = DuplicateKeysMutator(proportion=0.3, columns=["id"]).apply(_dataset(), rng=make_rng(1))
    assert out.frame["id"].nunique() < len(out.frame)  # the PK now has repeats


def test_orphan_fk_writes_values_with_no_parent() -> None:
    ds = _dataset()
    original = set(ds.frame["parent_id"].dropna())
    out, manifest = OrphanFkMutator(proportion=0.3).apply(ds, rng=make_rng(1))
    rows = [e["row"] for e in manifest.entries]
    injected = set(out.frame["parent_id"].iloc[rows])
    assert injected and not (injected & original)  # every injected FK is orphaned


def test_duplicate_keys_violates_composite_uniqueness() -> None:
    # regression (F1): a composite PK must be duplicated as a tuple, not per-column.
    schema = Schema(
        columns=(Column("a", LogicalType.INTEGER), Column("b", LogicalType.INTEGER)),
        primary_key=("a", "b"),
    )
    frame = pd.DataFrame(
        {"a": pd.array(range(30), dtype="Int64"), "b": pd.array(range(30), dtype="Int64")}
    )
    ds = Dataset(frame=frame, schema=schema)
    out, _ = DuplicateKeysMutator(proportion=0.1).apply(ds, rng=make_rng(0))
    assert out.frame.duplicated(subset=["a", "b"]).sum() > 0  # the composite key repeats


def test_duplicate_keys_on_non_unique_index_does_not_crash() -> None:
    # regression (F2): work positionally, not by index label.
    ds = Dataset(
        frame=pd.DataFrame({"id": pd.array([1, 2, 3, 4], dtype="Int64")}, index=[0, 0, 1, 1]),
        schema=Schema(
            columns=(Column("id", LogicalType.INTEGER, primary_key=True),), primary_key=("id",)
        ),
    )
    out, manifest = DuplicateKeysMutator(proportion=1.0).apply(ds, rng=make_rng(1))
    assert manifest.entries and out.frame["id"].nunique() == 1


def test_orphan_fk_string_sentinel_is_absent() -> None:
    # regression (F3): the string orphan must not collide with an existing value.
    frame = pd.DataFrame({"ref": ["__ORPHAN__", "x", "y", "z"]})
    ds = Dataset(frame=frame, schema=Schema(columns=(Column("ref", LogicalType.STRING),)))
    out, manifest = OrphanFkMutator(proportion=0.5, columns=["ref"]).apply(ds, rng=make_rng(1))
    rows = [e["row"] for e in manifest.entries]
    injected = set(out.frame["ref"].iloc[rows])
    assert injected and not (injected & {"__ORPHAN__", "x", "y", "z"})


@pytest.mark.parametrize(
    "mutator", [MissingFieldMutator, RenamedColumnMutator, DuplicateKeysMutator]
)
def test_targeting_unknown_column_raises(mutator) -> None:
    with pytest.raises(ChaosError, match="not in the dataset"):
        mutator(columns=["nope"]).apply(_dataset(), rng=make_rng(1))


def test_params_validation() -> None:
    from pydantic import ValidationError

    from tymi.chaos.mutators.schema_break import ExtraFieldParams, SchemaBreakParams

    with pytest.raises(ValidationError):
        SchemaBreakParams(proportion=1.5)
    with pytest.raises(ValidationError):
        SchemaBreakParams(bogus=1)  # extra keys forbidden
    with pytest.raises(ValidationError):
        ExtraFieldParams(field_name="")  # non-empty required


def test_faults_toggle_independently_via_chain() -> None:
    _, manifest = apply_chaos(
        _dataset(), resolve_mutators(["extra_field", "duplicate_keys"]), rng=make_rng(3)
    )
    assert sorted({e["fault_type"] for e in manifest.entries}) == ["duplicate_key", "extra_field"]
