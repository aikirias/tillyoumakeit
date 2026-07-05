"""PRD 1 Story 1.1: the GatedDataset load boundary (AD-21)."""

from __future__ import annotations

import pandas as pd
import pytest

from tymi.core.rng import make_rng
from tymi.domain.artifacts import (
    Column,
    Dataset,
    GatedDataset,
    GateReport,
    LeakageGuard,
    LogicalType,
    Schema,
    leakage_digest,
    require_gated,
)
from tymi.synth.leakage import gate_dataset

SALT = "fixed-test-salt"


def _dataset(frame: pd.DataFrame, columns: tuple[Column, ...]) -> Dataset:
    return Dataset(frame=frame, schema=Schema(columns=columns))


def _guard(values: list[str], column: str = "email", salt: str = SALT) -> LeakageGuard:
    return LeakageGuard(
        salt=salt, columns={column: tuple(sorted({leakage_digest(v, salt) for v in values}))}
    )


def _resample(name: str, count: int, rng) -> list[str]:
    return [f"synthetic{i}@x.com" for i in range(count)]


# --- AC-1: no public constructor (fail closed) ------------------------------


def test_gated_dataset_cannot_be_constructed_directly() -> None:
    ds = _dataset(pd.DataFrame({"email": ["a@x.com"]}), (Column("email", LogicalType.STRING),))
    with pytest.raises(TypeError, match="can only be produced by the leakage gate"):
        GatedDataset(ds, GateReport(), key=object())  # wrong key
    with pytest.raises(TypeError):  # missing key entirely
        GatedDataset(ds, GateReport())  # type: ignore[call-arg]


def test_replace_cannot_forge_a_gated_dataset() -> None:
    # dataclasses.replace() is the idiomatic "modified copy" — it must NOT be able to swap in
    # un-gated data, because the gate key is validated but never stored (AD-21).
    import dataclasses

    ds = _dataset(pd.DataFrame({"email": ["a@x.com"]}), (Column("email", LogicalType.STRING),))
    gated = gate_dataset(ds, None, rng=make_rng(0), resample=_resample)
    evil = _dataset(
        pd.DataFrame({"email": ["REAL_LEAKED@x.com"]}), (Column("email", LogicalType.STRING),)
    )
    with pytest.raises(TypeError):
        dataclasses.replace(gated, dataset=evil)


# --- AC-2: the gate produces one; the boundary rejects a raw Dataset --------


def test_gate_dataset_produces_a_gated_dataset() -> None:
    ds = _dataset(pd.DataFrame({"email": ["a@x.com"]}), (Column("email", LogicalType.STRING),))
    gated = gate_dataset(ds, None, rng=make_rng(0), resample=_resample)
    assert isinstance(gated, GatedDataset)


def test_require_gated_accepts_gated_rejects_raw() -> None:
    ds = _dataset(pd.DataFrame({"email": ["a@x.com"]}), (Column("email", LogicalType.STRING),))
    gated = gate_dataset(ds, None, rng=make_rng(0), resample=_resample)
    assert require_gated(gated) is gated
    with pytest.raises(TypeError, match="a GatedDataset is required at the load boundary"):
        require_gated(ds)  # a raw Dataset at the boundary is a type error


# --- AC-3: preserves Schema + carries the gate result -----------------------


def test_gated_dataset_preserves_schema_and_carries_report() -> None:
    schema_cols = (Column("email", LogicalType.STRING),)
    ds = _dataset(pd.DataFrame({"email": ["real@x.com"]}), schema_cols)
    guard = _guard(["real@x.com"])
    gated = gate_dataset(ds, guard, rng=make_rng(0), resample=_resample)
    assert gated.schema == Schema(columns=schema_cols)  # AD-10 preserved
    assert gated.report.columns_checked == ("email",)
    # convenience accessors mirror the wrapped Dataset
    assert list(gated.frame.columns) == ["email"]


def test_columns_checked_reflects_only_actually_gated_columns() -> None:
    # A guard column absent from the frame, or with an empty digest set, was never inspected.
    frame = pd.DataFrame({"email": ["a@x.com"]})
    ds = _dataset(frame, (Column("email", LogicalType.STRING),))
    guard = LeakageGuard(
        salt=SALT,
        columns={
            "email": tuple(sorted({leakage_digest("real@x.com", SALT)})),
            "absent": (leakage_digest("x", SALT),),  # not in the frame
            "empty": (),  # empty digest set
        },
    )
    gated = gate_dataset(ds, guard, rng=make_rng(0), resample=_resample)
    assert gated.report.columns_checked == ("email",)


def test_seal_is_independent_of_the_caller_input_frame() -> None:
    # The no-op gate returns the same object; the seal must copy so a caller mutating its
    # retained input can't alter the sealed contents.
    ds = _dataset(pd.DataFrame({"email": ["a@x.com"]}), (Column("email", LogicalType.STRING),))
    gated = gate_dataset(ds, None, rng=make_rng(0), resample=_resample)
    ds.frame.loc[0, "email"] = "MUTATED@x.com"
    assert gated.frame.loc[0, "email"] == "a@x.com"  # sealed copy is untouched


def test_gated_dataset_equality_and_hash_and_repr_are_safe() -> None:
    ds = _dataset(
        pd.DataFrame({"email": ["secret@x.com"]}), (Column("email", LogicalType.STRING),)
    )
    a = gate_dataset(ds, None, rng=make_rng(0), resample=_resample)
    b = gate_dataset(ds, None, rng=make_rng(0), resample=_resample)
    assert a == a and a != b  # identity equality, never raises on the inner DataFrame
    assert isinstance(hash(a), int)  # hashable (usable in a set/dict)
    assert "secret@x.com" not in repr(a)  # repr never dumps sensitive cell values


# --- AC-4: zero real values after sealing (inherits the gate) ---------------


def test_gate_dataset_removes_real_values() -> None:
    ds = _dataset(
        pd.DataFrame({"email": ["real@x.com", "safe@x.com", "real@x.com"]}),
        (Column("email", LogicalType.STRING),),
    )
    guard = _guard(["real@x.com"])
    gated = gate_dataset(ds, guard, rng=make_rng(0), resample=_resample)
    digest_set = set(guard.columns["email"])
    assert all(leakage_digest(v, SALT) not in digest_set for v in gated.frame["email"])
    assert "safe@x.com" in list(gated.frame["email"])  # non-colliding cell untouched


# --- determinism ------------------------------------------------------------


def test_gate_dataset_is_deterministic() -> None:
    def build() -> GatedDataset:
        ds = _dataset(
            pd.DataFrame({"email": ["real@x.com", "real@x.com"]}),
            (Column("email", LogicalType.STRING),),
        )
        return gate_dataset(ds, _guard(["real@x.com"]), rng=make_rng(7), resample=_resample)

    pd.testing.assert_frame_equal(build().frame, build().frame)
