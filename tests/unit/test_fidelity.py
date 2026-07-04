"""Story 2.7: fidelity report (in-house KSComplement/TVComplement/correlation)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tymi.core.rng import make_rng
from tymi.domain.artifacts import (
    Column,
    Dataset,
    FidelityReport,
    LogicalType,
    Schema,
    fidelity_report_to_json,
)
from tymi.eval.fidelity import (
    CORRELATION_KEY,
    correlation_similarity,
    fidelity_report,
    ks_complement,
    tv_complement,
)
from tymi.profiling.profiler import profile_dataset
from tymi.synth.generator import generate_faithful


def _source() -> Dataset:
    rng = np.random.default_rng(0)
    n = 500
    x = rng.normal(0, 1, n)
    frame = pd.DataFrame(
        {
            "age": rng.integers(18, 70, n),
            "score": x,
            "score2": x * 0.9 + rng.normal(0, 0.2, n),  # correlated with score
            "region": rng.choice(["LATAM", "EMEA", "APAC"], n, p=[0.5, 0.3, 0.2]),
        }
    )
    schema = Schema(
        columns=(
            Column("age", LogicalType.INTEGER),
            Column("score", LogicalType.FLOAT),
            Column("score2", LogicalType.FLOAT),
            Column("region", LogicalType.CATEGORICAL),
        )
    )
    return Dataset(frame=frame, schema=schema)


# --- metric unit tests ------------------------------------------------------


def test_tv_complement_identical_and_disjoint() -> None:
    ref = {"a": 60.0, "b": 40.0}
    assert tv_complement({"a": 6.0, "b": 4.0}, ref) == pytest.approx(1.0)  # same proportions
    assert tv_complement({"c": 10.0}, ref) == pytest.approx(0.0)  # disjoint categories
    assert tv_complement({}, ref) is None  # empty


def test_ks_complement_two_sample_high_and_low() -> None:
    rng = np.random.default_rng(1)
    ref = pd.Series(rng.normal(0, 1, 2000))
    same = pd.Series(rng.normal(0, 1, 2000))
    shifted = pd.Series(rng.normal(50, 1, 2000))
    assert ks_complement(ref, same) > 0.9  # same distribution → ~1
    assert ks_complement(ref, shifted) < 0.1  # disjoint → ~0
    assert ks_complement(pd.Series([], dtype=float), same) is None  # empty reference


def test_correlation_similarity_detects_preserved_and_broken() -> None:
    profile = profile_dataset(_source())
    # generated data that preserves the score/score2 correlation scores high
    good = generate_faithful(profile, rows=800, rng=make_rng(3))
    assert correlation_similarity(good, profile) > 0.7
    # independent columns (correlation destroyed) score lower
    rng = np.random.default_rng(4)
    broken = Dataset(
        frame=pd.DataFrame(
            {
                "age": rng.integers(18, 70, 800),
                "score": rng.normal(0, 1, 800),
                "score2": rng.normal(0, 1, 800),  # now independent of score
                "region": rng.choice(["LATAM", "EMEA", "APAC"], 800),
            }
        ),
        schema=profile.schema,
    )
    assert correlation_similarity(broken, profile) < correlation_similarity(good, profile)


# --- report assembly + pass/fail -------------------------------------------


def test_faithful_generation_passes_at_default_tolerance() -> None:
    profile = profile_dataset(_source())
    dataset = generate_faithful(profile, rows=1000, rng=make_rng(5))
    report = fidelity_report(profile, dataset)  # default tolerance 0.9
    assert report.passed
    assert not report.failures
    assert set(report.per_column) == {"age", "score", "score2", "region"}
    assert all(0.0 <= s <= 1.0 for s in report.per_column.values())
    assert report.global_correlation is not None


def test_constant_numeric_column_scores_high() -> None:
    # regression (HIGH): a faithfully-reproduced constant column must not false-fail.
    frame = pd.DataFrame({"flag": [5.0] * 200, "x": np.random.default_rng(0).normal(0, 1, 200)})
    schema = Schema(columns=(Column("flag", LogicalType.FLOAT), Column("x", LogicalType.FLOAT)))
    profile = profile_dataset(Dataset(frame, schema))
    gen = generate_faithful(profile, rows=300, rng=make_rng(1))
    report = fidelity_report(profile, gen, tolerance=0.9)
    assert report.per_column["flag"] > 0.9  # was 0.0 under one-sample-vs-histogram
    assert "flag" not in report.failures


def test_low_cardinality_integer_column_scores_high() -> None:
    # regression (HIGH): a discrete integer column must not false-fail the default gate.
    rng = np.random.default_rng(2)
    frame = pd.DataFrame({"tier": rng.integers(1, 4, 400), "x": rng.normal(0, 1, 400)})
    schema = Schema(columns=(Column("tier", LogicalType.INTEGER), Column("x", LogicalType.FLOAT)))
    profile = profile_dataset(Dataset(frame, schema))
    gen = generate_faithful(profile, rows=600, rng=make_rng(3))
    assert fidelity_report(profile, gen, tolerance=0.9).per_column["tier"] > 0.9


def test_seasonal_datetime_column_does_not_false_fail() -> None:
    # regression (HIGH): the generator samples datetimes uniformly across the range and
    # does not reproduce monthly seasonality, so fidelity compares against a reference
    # drawn the same way — a faithful datetime column must not false-fail.
    rng = np.random.default_rng(4)
    winter = pd.to_datetime("2021-12-15") + pd.to_timedelta(rng.integers(0, 20, 300), unit="D")
    frame = pd.DataFrame({"ts": winter})
    schema = Schema(columns=(Column("ts", LogicalType.DATETIME),))
    profile = profile_dataset(Dataset(frame, schema))
    gen = generate_faithful(profile, rows=400, rng=make_rng(5))
    report = fidelity_report(profile, gen, tolerance=0.8)
    assert "ts" in report.per_column and report.per_column["ts"] > 0.8


def test_mismatched_dataset_fails_and_lists_columns() -> None:
    profile = profile_dataset(_source())
    rng = np.random.default_rng(6)
    # region categories entirely different + score shifted far away
    bad = Dataset(
        frame=pd.DataFrame(
            {
                "age": rng.integers(18, 70, 500),
                "score": rng.normal(100, 1, 500),  # far from source ~N(0,1)
                "score2": rng.normal(100, 1, 500),
                "region": ["ZZZ"] * 500,  # unseen category
            }
        ),
        schema=profile.schema,
    )
    report = fidelity_report(profile, bad, tolerance=0.9)
    assert not report.passed
    assert "score" in report.failures and "region" in report.failures


def test_deterministic_report_same_seed() -> None:
    profile = profile_dataset(_source())
    da = generate_faithful(profile, rows=400, rng=make_rng(7))
    db = generate_faithful(profile, rows=400, rng=make_rng(7))
    ra = fidelity_report(profile, da, tolerance=0.7)
    rb = fidelity_report(profile, db, tolerance=0.7)
    assert ra == rb


def test_report_json_is_exportable_and_round_trips() -> None:
    report = FidelityReport(
        per_column={"a": 0.95, "b": 0.8},
        global_correlation=0.99,
        tolerance=0.9,
        passed=False,
        failures=("b",),
        skipped=("note",),
    )
    import json

    payload = fidelity_report_to_json(report)
    data = json.loads(payload)
    assert data["per_column"] == {"a": 0.95, "b": 0.8}
    assert data["passed"] is False and data["failures"] == ["b"]


def test_empty_report_does_not_pass() -> None:
    # regression (MEDIUM/HIGH): a dataset sharing no columns with the Profile must NOT
    # pass — that would green-light a wrong/empty dataset through a CI gate.
    profile = profile_dataset(_source())
    unrelated = Dataset(
        frame=pd.DataFrame({"zzz": [1, 2, 3]}),
        schema=Schema(columns=(Column("zzz", LogicalType.INTEGER),)),
    )
    report = fidelity_report(profile, unrelated, tolerance=0.9)
    assert not report.per_column and report.global_correlation is None
    assert not report.passed


def test_global_correlation_none_with_single_numeric_column() -> None:
    frame = pd.DataFrame({"x": np.random.default_rng(0).normal(0, 1, 200)})
    schema = Schema(columns=(Column("x", LogicalType.FLOAT),))
    profile = profile_dataset(Dataset(frame, schema))
    gen = generate_faithful(profile, rows=200, rng=make_rng(1))
    assert fidelity_report(profile, gen, tolerance=0.7).global_correlation is None


def test_boolean_column_is_scored_via_tv() -> None:
    rng = np.random.default_rng(0)
    frame = pd.DataFrame({"active": rng.choice([True, False], 300, p=[0.7, 0.3])})
    schema = Schema(columns=(Column("active", LogicalType.BOOLEAN),))
    profile = profile_dataset(Dataset(frame, schema))
    gen = generate_faithful(profile, rows=400, rng=make_rng(1))
    report = fidelity_report(profile, gen, tolerance=0.8)
    assert "active" in report.per_column and report.per_column["active"] > 0.8


def test_text_columns_are_skipped() -> None:
    frame = pd.DataFrame({"bio": [f"a long free-text value number {i}" for i in range(60)]})
    dataset = Dataset(frame=frame, schema=Schema(columns=(Column("bio", LogicalType.STRING),)))
    profile = profile_dataset(dataset)  # long strings → text stats only
    report = fidelity_report(profile, dataset, tolerance=0.9)
    assert "bio" in report.skipped
    assert "bio" not in report.per_column


def test_correlation_key_flags_broken_correlation() -> None:
    profile = profile_dataset(_source())
    rng = np.random.default_rng(8)
    broken = Dataset(
        frame=pd.DataFrame(
            {
                "age": rng.integers(18, 70, 600),
                "score": rng.normal(0, 1, 600),
                "score2": rng.normal(0, 1, 600),  # independent
                "region": rng.choice(["LATAM", "EMEA", "APAC"], 600, p=[0.5, 0.3, 0.2]),
            }
        ),
        schema=profile.schema,
    )
    report = fidelity_report(profile, broken, tolerance=0.95)
    assert CORRELATION_KEY in report.failures


# --- CLI (CI gate) ----------------------------------------------------------


def _saved(tmp_path):
    from tymi.profiling.profile_io import save_profile

    path = tmp_path / "p.yaml"
    save_profile(profile_dataset(_source()), path)
    return path


def test_cli_report_fidelity_passes_exit_0(tmp_path) -> None:
    from typer.testing import CliRunner

    from tymi.cli.app import app

    result = CliRunner().invoke(
        app,
        ["report", "--fidelity", "-p", str(_saved(tmp_path)), "-n", "800", "--tolerance", "0.6"],
    )
    assert result.exit_code == 0, result.stdout
    assert '"passed": true' in result.stdout


def test_cli_report_fidelity_fails_exit_1(tmp_path) -> None:
    from typer.testing import CliRunner

    from tymi.cli.app import app

    # tolerance 1.0 is unreachable (finite-sample KS noise) → CI gate trips
    result = CliRunner().invoke(
        app,
        ["report", "--fidelity", "-p", str(_saved(tmp_path)), "-n", "500", "--tolerance", "1.0"],
    )
    assert result.exit_code == 1


def test_cli_report_without_fidelity_flag_errors(tmp_path) -> None:
    from typer.testing import CliRunner

    from tymi.cli.app import app

    result = CliRunner().invoke(app, ["report", "-p", str(_saved(tmp_path))])
    assert result.exit_code == 2
    assert "only --fidelity" in result.stdout


def test_cli_report_from_data_parquet_and_out(tmp_path) -> None:
    from typer.testing import CliRunner

    from tymi.cli.app import app
    from tymi.io.exporters import ParquetExporter

    profile_path = _saved(tmp_path)
    # export a faithful dataset to parquet, then report on it via --data
    profile = profile_dataset(_source())
    dataset = generate_faithful(profile, rows=800, rng=make_rng(5))
    data_path = tmp_path / "gen.parquet"
    ParquetExporter().export(dataset, target=str(data_path))
    out_path = tmp_path / "rep.json"
    result = CliRunner().invoke(
        app,
        [
            "report", "--fidelity", "-p", str(profile_path),
            "--data", str(data_path), "--tolerance", "0.7", "-o", str(out_path),
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert out_path.exists()
    import json

    written = json.loads(out_path.read_text())
    assert written["passed"] is True and set(written["per_column"])  # non-empty
