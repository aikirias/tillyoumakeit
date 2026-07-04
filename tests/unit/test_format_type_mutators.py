"""Story 3.3: format and type violation mutators (five toggleable faults)."""

from __future__ import annotations

import pandas as pd
import pytest
from pydantic import ValidationError

from tymi.chaos.engine import apply_chaos, resolve_mutators
from tymi.chaos.mutators.format_type import (
    BrokenEncodingMutator,
    IllegalNullMutator,
    InvalidDateMutator,
    OversizedStringMutator,
    OversizedStringParams,
    TextInNumericMutator,
)
from tymi.core.errors import ChaosError
from tymi.core.plugins import load_mutators
from tymi.core.rng import make_rng
from tymi.domain.artifacts import Column, Dataset, LogicalType, Schema
from tymi.ports import Mutator

_MUTATORS = {
    "text_in_numeric": TextInNumericMutator,
    "invalid_date": InvalidDateMutator,
    "broken_encoding": BrokenEncodingMutator,
    "oversized_string": OversizedStringMutator,
    "illegal_null": IllegalNullMutator,
}


def _dataset(n: int = 60) -> Dataset:
    frame = pd.DataFrame(
        {
            "age": pd.array(range(n), dtype="Int64"),
            "when": pd.to_datetime("2021-01-01") + pd.to_timedelta(range(n), unit="D"),
            "email": [f"u{i}@x.com" for i in range(n)],
            "pk": pd.array(range(n), dtype="Int64"),
        }
    )
    schema = Schema(
        columns=(
            Column("age", LogicalType.INTEGER),
            Column("when", LogicalType.DATETIME),
            Column("email", LogicalType.STRING),
            Column("pk", LogicalType.INTEGER, nullable=False),
        )
    )
    return Dataset(frame=frame, schema=schema)


# --- each fault appears + registered + deterministic (AC-1, AC-2) -----------


@pytest.mark.parametrize("name", list(_MUTATORS))
def test_each_mutator_registered_under_entry_point(name: str) -> None:
    assert load_mutators().get(name) is _MUTATORS[name]


@pytest.mark.parametrize("name", list(_MUTATORS))
def test_each_fault_appears_in_output_and_manifest(name: str) -> None:
    ds = _dataset()
    out, manifest = apply_chaos(ds, resolve_mutators([name]), rng=make_rng(1))
    assert manifest.entries, f"{name} produced no faults"
    assert all(e["fault_type"] == name for e in manifest.entries)
    # every recorded fault is actually in the output frame at that cell
    for e in manifest.entries:
        cell = out.frame.iloc[e["row"]][e["column"]]
        if name == "illegal_null":
            assert pd.isna(cell)
        else:
            assert not pd.isna(cell)


@pytest.mark.parametrize("name", list(_MUTATORS))
def test_each_mutator_is_deterministic(name: str) -> None:
    ds = _dataset()
    a_ds, a_man = apply_chaos(ds, resolve_mutators([name]), rng=make_rng(5))
    b_ds, b_man = apply_chaos(ds, resolve_mutators([name]), rng=make_rng(5))
    assert a_man.entries == b_man.entries
    pd.testing.assert_frame_equal(a_ds.frame, b_ds.frame)


@pytest.mark.parametrize("name", list(_MUTATORS))
def test_each_mutator_satisfies_port(name: str) -> None:
    assert isinstance(_MUTATORS[name](), Mutator)


# --- specific fault semantics -----------------------------------------------


def test_text_in_numeric_targets_numeric_and_writes_text() -> None:
    ds = _dataset()
    out, manifest = TextInNumericMutator(proportion=0.2).apply(ds, rng=make_rng(1))
    assert {e["column"] for e in manifest.entries} == {"age", "pk"}  # both numeric
    rows = [(e["row"], e["column"]) for e in manifest.entries]
    r, c = rows[0]
    assert isinstance(out.frame.iloc[r][c], str)  # a string now lives in a numeric column


def test_oversized_string_size_param() -> None:
    ds = _dataset()
    out, manifest = OversizedStringMutator(proportion=0.1, size=500).apply(ds, rng=make_rng(1))
    r, c = manifest.entries[0]["row"], manifest.entries[0]["column"]
    assert len(out.frame.iloc[r][c]) == 500


def test_illegal_null_defaults_to_non_nullable_columns() -> None:
    ds = _dataset()
    out, manifest = IllegalNullMutator(proportion=0.2).apply(ds, rng=make_rng(1))
    assert {e["column"] for e in manifest.entries} == {"pk"}  # only the non-nullable column
    rows = [e["row"] for e in manifest.entries]
    assert out.frame["pk"].iloc[rows].isna().all()


def test_broken_encoding_targets_text_only() -> None:
    ds = _dataset()
    _, manifest = BrokenEncodingMutator(proportion=0.2).apply(ds, rng=make_rng(1))
    assert {e["column"] for e in manifest.entries} == {"email"}


# --- targeting + non-null (AC-3) --------------------------------------------


def test_wrong_type_target_raises() -> None:
    with pytest.raises(ChaosError, match="cannot target column 'email'"):
        TextInNumericMutator(columns=["email"]).apply(_dataset(), rng=make_rng(1))
    with pytest.raises(ChaosError, match="cannot target column 'age'"):
        BrokenEncodingMutator(columns=["age"]).apply(_dataset(), rng=make_rng(1))


def test_non_targets_untouched() -> None:
    ds = _dataset()
    out, _ = TextInNumericMutator(proportion=0.2, columns=["age"]).apply(ds, rng=make_rng(1))
    assert out.frame["email"].equals(ds.frame["email"])
    assert out.frame["pk"].equals(ds.frame["pk"])


def test_format_faults_preserve_existing_nulls() -> None:
    frame = pd.DataFrame({"email": ["a@x.com", None, "b@x.com", None] * 15})
    ds = Dataset(frame=frame, schema=Schema(columns=(Column("email", LogicalType.STRING),)))
    before_nulls = int(ds.frame["email"].isna().sum())
    out, _ = OversizedStringMutator(proportion=0.5).apply(ds, rng=make_rng(1))
    assert int(out.frame["email"].isna().sum()) == before_nulls  # nulls not corrupted


def test_schema_preserved_though_dtype_degrades() -> None:
    ds = _dataset()
    out, _ = TextInNumericMutator(proportion=0.1, columns=["age"]).apply(ds, rng=make_rng(1))
    assert out.schema == ds.schema  # canonical Schema intact (AD-10)
    assert out.frame["age"].dtype == object  # dtype legitimately degraded


# --- independent toggling via the chain (AC-1) ------------------------------


def test_faults_toggle_independently_via_chain() -> None:
    ds = _dataset()
    _, manifest = apply_chaos(
        ds, resolve_mutators(["text_in_numeric", "illegal_null"]), rng=make_rng(3)
    )
    assert sorted({e["fault_type"] for e in manifest.entries}) == [
        "illegal_null",
        "text_in_numeric",
    ]


def test_params_validation() -> None:
    with pytest.raises(ValidationError):
        TextInNumericMutator(proportion=2.0)
    with pytest.raises(ValidationError):
        OversizedStringParams(size=0)
    with pytest.raises(ValidationError):
        OversizedStringParams(size=20_000_000)  # regression (F3): size is capped at 10 MB


def test_broken_encoding_output_is_exportable() -> None:
    # regression (F1): broken-encoding chaos data must survive export (a lone surrogate
    # would crash CSV/JSON/Parquet). All tokens are valid, if corrupt, UTF-8.
    from tymi.io.exporters import CsvExporter, JsonExporter

    frame = pd.DataFrame({"e": [f"u{i}@x.com" for i in range(40)]}, dtype=object)
    ds = Dataset(frame=frame, schema=Schema(columns=(Column("e", LogicalType.STRING),)))
    out, _ = BrokenEncodingMutator(proportion=1.0).apply(ds, rng=make_rng(1))
    assert CsvExporter().render(out)  # no UnicodeEncodeError
    assert JsonExporter().render(out)


def test_small_column_is_not_a_silent_no_op() -> None:
    # regression (F2): a positive proportion on a small column injects >= 1 fault
    # (round(0.05*10) would otherwise be 0).
    ds = Dataset(
        frame=pd.DataFrame({"v": pd.array(range(10), dtype="Int64")}),
        schema=Schema(columns=(Column("v", LogicalType.INTEGER),)),
    )
    _, manifest = TextInNumericMutator(proportion=0.05).apply(ds, rng=make_rng(1))
    assert len(manifest.entries) >= 1


def test_manifest_value_is_bounded() -> None:
    # regression (Auditor): a 10k oversized string must not bloat the manifest.
    ds = _dataset()
    _, manifest = OversizedStringMutator(proportion=0.1, size=10_000).apply(ds, rng=make_rng(1))
    assert max(len(e["value"]) for e in manifest.entries) <= 80


def test_manifest_count_matches_cell_count() -> None:
    ds = _dataset()  # email has 60 non-null cells
    _, manifest = BrokenEncodingMutator(proportion=0.2).apply(ds, rng=make_rng(1))
    assert len(manifest.entries) == round(0.2 * 60)
