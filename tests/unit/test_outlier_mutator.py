"""Story 3.2: out-of-distribution fault mutator (OutlierMutator)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from tymi.chaos.engine import apply_chaos, resolve_mutators
from tymi.chaos.mutators.outlier import OutlierMutator, OutlierParams
from tymi.core.errors import ChaosError
from tymi.core.plugins import load_mutators
from tymi.core.rng import make_rng
from tymi.domain.artifacts import Column, Dataset, LogicalType, Schema
from tymi.ports import Mutator


def _dataset(n: int = 200) -> Dataset:
    rng = np.random.default_rng(0)
    frame = pd.DataFrame(
        {
            "age": pd.array(rng.integers(20, 70, n), dtype="Int64"),
            "score": rng.normal(0.0, 1.0, n),
            "when": pd.to_datetime("2021-01-01")
            + pd.to_timedelta(rng.integers(0, 365, n), unit="D"),
            "name": ["x"] * n,
        }
    )
    schema = Schema(
        columns=(
            Column("age", LogicalType.INTEGER),
            Column("score", LogicalType.FLOAT),
            Column("when", LogicalType.DATETIME),
            Column("name", LogicalType.STRING),
        )
    )
    return Dataset(frame=frame, schema=schema)


def _entries_for(manifest, column):
    return [e for e in manifest.entries if e["column"] == column]


# --- proportion + targeting (AC-2, AC-3) ------------------------------------


def test_proportion_is_honored_within_margin() -> None:
    ds = _dataset(500)
    _, manifest = OutlierMutator(proportion=0.1, columns=["score"]).apply(ds, rng=make_rng(1))
    realised = len(_entries_for(manifest, "score")) / 500
    assert abs(realised - 0.1) <= 0.02  # within the ±2pp acceptance margin


def test_default_targets_all_numeric_and_datetime_not_text() -> None:
    ds = _dataset()
    out, manifest = OutlierMutator(proportion=0.1).apply(ds, rng=make_rng(1))
    hit = {e["column"] for e in manifest.entries}
    assert hit == {"age", "score", "when"}  # numeric + datetime, never the string column
    assert (out.frame["name"] == ds.frame["name"]).all()  # non-target untouched


def test_explicit_columns_target_only_those() -> None:
    ds = _dataset()
    out, manifest = OutlierMutator(proportion=0.2, columns=["age"]).apply(ds, rng=make_rng(2))
    assert {e["column"] for e in manifest.entries} == {"age"}
    assert out.frame["score"].equals(ds.frame["score"])  # score untouched


def test_targeting_non_numeric_column_raises() -> None:
    with pytest.raises(ChaosError, match="not numeric or datetime"):
        OutlierMutator(columns=["name"]).apply(_dataset(), rng=make_rng(1))


def test_targeting_unknown_column_raises() -> None:
    with pytest.raises(ChaosError, match="not in the dataset schema"):
        OutlierMutator(columns=["nope"]).apply(_dataset(), rng=make_rng(1))


def test_target_in_schema_but_absent_from_frame_raises() -> None:
    # regression (M2): a schema/frame divergence must raise ChaosError, not KeyError.
    ds = Dataset(
        frame=pd.DataFrame({"b": [1, 2, 3]}),
        schema=Schema(
            columns=(Column("a", LogicalType.INTEGER), Column("b", LogicalType.INTEGER))
        ),
    )
    with pytest.raises(ChaosError, match="not present in the dataset frame"):
        OutlierMutator(columns=["a"]).apply(ds, rng=make_rng(1))


def test_duplicate_target_columns_are_deduped() -> None:
    # regression (M1): a column named twice must not double-mutate / duplicate entries.
    ds = Dataset(
        frame=pd.DataFrame({"a": pd.array(range(10), dtype="Int64")}),
        schema=Schema(columns=(Column("a", LogicalType.INTEGER),)),
    )
    _, manifest = OutlierMutator(proportion=0.5, columns=["a", "a"]).apply(ds, rng=make_rng(1))
    keys = [(e["row"], e["column"]) for e in manifest.entries]
    assert len(keys) == len(set(keys)) == 5  # one entry per cell, no duplicates


# --- out-of-range values + dtypes (AC-1, AC-5) ------------------------------


def test_injected_numeric_values_are_out_of_range() -> None:
    ds = _dataset(300)
    lo, hi = ds.frame["score"].min(), ds.frame["score"].max()
    out, manifest = OutlierMutator(proportion=0.15, columns=["score"]).apply(ds, rng=make_rng(3))
    rows = [e["row"] for e in _entries_for(manifest, "score")]
    injected = out.frame["score"].iloc[rows]
    assert ((injected < lo) | (injected > hi)).all()  # every injected value is outside [lo,hi]


def test_small_magnitude_integer_is_still_out_of_range() -> None:
    # regression (H1): a small magnitude must not round the "outlier" back onto a bound.
    ds = Dataset(
        frame=pd.DataFrame({"v": pd.array([10, 11, 12], dtype="Int64")}),
        schema=Schema(columns=(Column("v", LogicalType.INTEGER),)),
    )
    out, _ = OutlierMutator(proportion=1.0, magnitude=0.1).apply(ds, rng=make_rng(1))
    assert all(v < 10 or v > 12 for v in out.frame["v"].tolist())


def test_large_integer_column_does_not_overflow() -> None:
    # regression (H2): a big-valued int column at default magnitude must not crash.
    ds = Dataset(
        frame=pd.DataFrame({"v": pd.array([0, 3_000_000_000_000_000_000], dtype="Int64")}),
        schema=Schema(columns=(Column("v", LogicalType.INTEGER),)),
    )
    out, _ = OutlierMutator(proportion=1.0).apply(ds, rng=make_rng(1))  # no OverflowError
    assert out.frame["v"].dtype == "Int64"


def test_outlier_skips_column_with_no_numeric_values() -> None:
    # regression: a column already corrupted to text (e.g. by text_in_numeric earlier in
    # a chain) has no numeric anchor — outlier must skip it, not crash on min/max of [].
    ds = Dataset(
        frame=pd.DataFrame({"age": ["N/A", "oops", "text"]}, dtype=object),
        schema=Schema(columns=(Column("age", LogicalType.INTEGER),)),
    )
    out, manifest = OutlierMutator(proportion=1.0).apply(ds, rng=make_rng(1))
    assert manifest.entries == []  # nothing numeric to outlier
    assert out.frame["age"].tolist() == ["N/A", "oops", "text"]


def test_nulls_are_preserved_not_overwritten() -> None:
    # regression: outliers replace observed values only; nulls survive.
    ds = Dataset(
        frame=pd.DataFrame({"v": pd.array([1, 2, None, 4, None, 6, 7, 8, 9, 10], dtype="Int64")}),
        schema=Schema(columns=(Column("v", LogicalType.INTEGER),)),
    )
    before = int(ds.frame["v"].isna().sum())
    out, _ = OutlierMutator(proportion=0.5).apply(ds, rng=make_rng(1))
    assert int(out.frame["v"].isna().sum()) == before == 2


def test_integer_dtype_and_schema_preserved() -> None:
    ds = _dataset()
    out, _ = OutlierMutator(proportion=0.1, columns=["age"]).apply(ds, rng=make_rng(1))
    assert out.frame["age"].dtype == "Int64"  # AD-10 dtype preserved
    assert out.schema == ds.schema


def test_datetime_outliers_are_out_of_range() -> None:
    ds = _dataset(200)
    lo, hi = ds.frame["when"].min(), ds.frame["when"].max()
    out, manifest = OutlierMutator(proportion=0.1, columns=["when"]).apply(ds, rng=make_rng(4))
    rows = [e["row"] for e in _entries_for(manifest, "when")]
    injected = out.frame["when"].iloc[rows]
    assert ((injected < lo) | (injected > hi)).all()
    assert all(e["fault_type"] == "datetime_outlier" for e in _entries_for(manifest, "when"))


# --- manifest + determinism (AC-4, AC-5) ------------------------------------


def test_manifest_entry_shape_and_count() -> None:
    ds = _dataset()
    _, manifest = OutlierMutator(proportion=0.1, columns=["score"]).apply(ds, rng=make_rng(1))
    assert len(manifest.entries) == round(0.1 * 200)
    entry = manifest.entries[0]
    assert set(entry) == {"mutator", "row", "column", "fault_type", "value"}
    assert entry["mutator"] == "outlier" and entry["fault_type"] == "numeric_outlier"


def test_deterministic_same_seed() -> None:
    ds = _dataset()
    a_frame, a_man = OutlierMutator(proportion=0.1).apply(ds, rng=make_rng(9))
    b_frame, b_man = OutlierMutator(proportion=0.1).apply(ds, rng=make_rng(9))
    assert a_man.entries == b_man.entries
    pd.testing.assert_frame_equal(a_frame.frame, b_frame.frame)


def test_zero_proportion_is_a_no_op() -> None:
    ds = _dataset()
    out, manifest = OutlierMutator(proportion=0.0).apply(ds, rng=make_rng(1))
    assert manifest.entries == []
    pd.testing.assert_frame_equal(out.frame, ds.frame)


def test_caller_dataset_not_mutated() -> None:
    ds = _dataset()
    before = ds.frame["score"].tolist()
    OutlierMutator(proportion=0.2).apply(ds, rng=make_rng(1))
    assert ds.frame["score"].tolist() == before  # mutator copies its own frame


# --- params + discovery (AC-6) ----------------------------------------------


def test_params_are_validated() -> None:
    with pytest.raises(ValidationError):
        OutlierParams(proportion=1.5)
    with pytest.raises(ValidationError):
        OutlierParams(magnitude=0.0)


def test_no_arg_construction_uses_defaults() -> None:
    m = OutlierMutator()
    assert m.params.proportion == 0.05 and m.params.columns is None
    assert isinstance(m, Mutator)


def test_registered_under_entry_point_and_runs_via_engine() -> None:
    assert load_mutators().get("outlier") is OutlierMutator
    # entry-point discovery → default params → runs through the Story 3.1 engine
    mutators = resolve_mutators(["outlier"])
    out, manifest = apply_chaos(_dataset(), mutators, rng=make_rng(1))
    assert manifest.entries  # default 5% of numeric/datetime cells corrupted
    assert out.schema == _dataset().schema
