"""Story 4.3: composite Quality Score + membership + attribute-inference metrics."""

from __future__ import annotations

import json

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
    quality_privacy_report_to_json,
)
from tymi.eval.privacy_report import (
    attribute_inference_risk,
    membership_risk,
    quality_privacy_report,
    quality_score,
)
from tymi.profiling.profiler import profile_dataset
from tymi.synth.generator import generate_faithful

SALT = "fixed-test-salt"


def _source() -> Dataset:
    rng = np.random.default_rng(0)
    n = 400
    x = rng.normal(0, 1, n)
    frame = pd.DataFrame(
        {
            "age": rng.integers(18, 70, n),
            "score": x,
            "score2": x * 0.9 + rng.normal(0, 0.2, n),  # correlated with score
            "region": rng.choice(["LATAM", "EMEA", "APAC"], n, p=[0.5, 0.3, 0.2]),
            "email": [f"user{i}@x.com" for i in range(n)],  # unique → sensitive
        }
    )
    schema = Schema(
        columns=(
            Column("age", LogicalType.INTEGER),
            Column("score", LogicalType.FLOAT),
            Column("score2", LogicalType.FLOAT),
            Column("region", LogicalType.CATEGORICAL),
            Column("email", LogicalType.STRING),
        )
    )
    return Dataset(frame=frame, schema=schema)


# --- composite quality score (AC-1) -----------------------------------------


def test_quality_score_is_mean_of_fidelity_components() -> None:
    fidelity = FidelityReport(
        per_column={"a": 0.8, "b": 1.0}, global_correlation=0.6
    )
    assert quality_score(fidelity) == pytest.approx((0.8 + 1.0 + 0.6) / 3)


def test_quality_score_none_when_nothing_comparable() -> None:
    assert quality_score(FidelityReport(per_column={}, global_correlation=None)) is None


def test_faithful_generation_scores_high_quality() -> None:
    source = _source()
    profile = profile_dataset(source, sensitive_columns=["email"], salt=SALT)
    generated = generate_faithful(profile, rows=400, rng=make_rng(1))
    report = quality_privacy_report(profile, generated, tolerance=0.8)
    assert report.quality_score is not None and report.quality_score >= 0.8


# --- membership metric (AC-2) -----------------------------------------------


def test_membership_metric_flags_leaked_values() -> None:
    source = _source()
    profile = profile_dataset(source, sensitive_columns=["email"], salt=SALT)
    # A dataset that verbatim reproduces real emails → membership disclosure.
    leaky = Dataset(
        frame=pd.DataFrame({"email": ["user0@x.com", "user1@x.com", "brand-new@x.com"]}),
        schema=Schema(columns=(Column("email", LogicalType.STRING),)),
    )
    risk = membership_risk(profile, leaky)
    assert risk == pytest.approx(2 / 3)  # 2 of 3 reproduce a real value


def test_membership_metric_zero_on_gated_faithful_output() -> None:
    source = _source()
    profile = profile_dataset(source, sensitive_columns=["email"], salt=SALT)
    generated = generate_faithful(profile, rows=300, rng=make_rng(2))
    # The Story 2.5 gate suppressed real values → no membership disclosure.
    assert membership_risk(profile, generated) == 0.0


def test_membership_metric_reports_worst_column_not_pooled_average() -> None:
    # Two sensitive columns: one 100% leaked, one 100% novel. A pooled average would
    # report 0.5 and mask the fully-compromised column; the worst-column rate is 1.0.
    frame = pd.DataFrame({"leak": ["a", "b"], "safe": ["x", "y"]})
    schema = Schema(
        columns=(Column("leak", LogicalType.STRING), Column("safe", LogicalType.STRING))
    )
    profile = profile_dataset(
        Dataset(frame=frame, schema=schema), sensitive_columns=["leak", "safe"], salt=SALT
    )
    generated = Dataset(
        frame=pd.DataFrame({"leak": ["a", "b"], "safe": ["new1", "new2"]}), schema=schema
    )
    assert membership_risk(profile, generated) == pytest.approx(1.0)


def test_attribute_inference_skips_unsupported_near_unique_predictor() -> None:
    # 40 rows, both columns all-distinct (≤ cap but avg group size 1): a near-unique
    # predictor must NOT saturate the metric to 1.0 — it has no real support.
    frame = pd.DataFrame(
        {"secret": [f"s{i}" for i in range(40)], "qi": [f"q{i}" for i in range(40)]}
    )
    schema = Schema(
        columns=(
            Column("secret", LogicalType.CATEGORICAL),
            Column("qi", LogicalType.CATEGORICAL),
        )
    )
    assert attribute_inference_risk(Dataset(frame=frame, schema=schema), ["secret"]) is None


def test_membership_metric_none_without_sensitive_columns() -> None:
    source = _source()
    profile = profile_dataset(source, salt=SALT)  # no sensitive columns → no guard
    generated = generate_faithful(profile, rows=100, rng=make_rng(3))
    assert membership_risk(profile, generated) is None


def test_membership_metric_handles_int64_null_without_false_negative() -> None:
    # Regression (Story 2.6): a nullable Int64 with pd.NA must hash as "100", not "100.0",
    # or a real leaked integer id slips past the membership check.
    frame = pd.DataFrame({"acct": pd.array([100, 200, None], dtype="Int64")})
    schema = Schema(columns=(Column("acct", LogicalType.INTEGER),))
    profile = profile_dataset(
        Dataset(frame=frame, schema=schema), sensitive_columns=["acct"], salt=SALT
    )
    leaky = Dataset(
        frame=pd.DataFrame({"acct": pd.array([100, 999, None], dtype="Int64")}),
        schema=schema,
    )
    # 100 leaks, 999 is novel, None is skipped → 1 of 2 non-null.
    assert membership_risk(profile, leaky) == pytest.approx(0.5)


# --- attribute-inference metric (AC-3) --------------------------------------


def test_attribute_inference_reflects_strong_numeric_correlation() -> None:
    n = 300
    x = np.linspace(0, 1, n)
    frame = pd.DataFrame({"secret": x, "qi": x * 2 + 0.01})  # near-perfectly correlated
    schema = Schema(
        columns=(Column("secret", LogicalType.FLOAT), Column("qi", LogicalType.FLOAT))
    )
    risk = attribute_inference_risk(Dataset(frame=frame, schema=schema), ["secret"])
    assert risk is not None and risk > 0.95


def test_attribute_inference_low_for_independent_columns() -> None:
    rng = np.random.default_rng(4)
    frame = pd.DataFrame({"secret": rng.normal(0, 1, 500), "qi": rng.normal(0, 1, 500)})
    schema = Schema(
        columns=(Column("secret", LogicalType.FLOAT), Column("qi", LogicalType.FLOAT))
    )
    risk = attribute_inference_risk(Dataset(frame=frame, schema=schema), ["secret"])
    assert risk is not None and risk < 0.3


def test_attribute_inference_categorical_conditional_mode() -> None:
    # secret is perfectly determined by qi → an attacker who knows qi infers secret.
    frame = pd.DataFrame({"secret": ["A", "A", "B", "B"] * 25, "qi": ["p", "p", "q", "q"] * 25})
    schema = Schema(
        columns=(
            Column("secret", LogicalType.CATEGORICAL),
            Column("qi", LogicalType.CATEGORICAL),
        )
    )
    risk = attribute_inference_risk(Dataset(frame=frame, schema=schema), ["secret"])
    assert risk == pytest.approx(1.0)


def test_attribute_inference_none_without_sensitive_columns() -> None:
    frame = pd.DataFrame({"a": [1.0, 2.0], "b": [3.0, 4.0]})
    schema = Schema(columns=(Column("a", LogicalType.FLOAT), Column("b", LogicalType.FLOAT)))
    assert attribute_inference_risk(Dataset(frame=frame, schema=schema), []) is None


# --- composition / gate / export (AC-4, AC-5) -------------------------------


def test_report_passes_and_fails_on_configurable_gates() -> None:
    source = _source()
    profile = profile_dataset(source, sensitive_columns=["email"], salt=SALT)
    generated = generate_faithful(profile, rows=400, rng=make_rng(5))

    ok = quality_privacy_report(profile, generated, tolerance=0.8)
    assert ok.passed and not ok.failures

    # Impossible quality bar → quality gate trips.
    strict = quality_privacy_report(profile, generated, tolerance=1.01)
    assert not strict.passed and "quality" in strict.failures


def test_report_membership_gate_trips_on_leak() -> None:
    source = _source()
    profile = profile_dataset(source, sensitive_columns=["email"], salt=SALT)
    leaky = Dataset(
        frame=pd.DataFrame({"email": ["user0@x.com", "user1@x.com"]}),
        schema=Schema(columns=(Column("email", LogicalType.STRING),)),
    )
    report = quality_privacy_report(profile, leaky, tolerance=0.0, membership_threshold=0.0)
    assert not report.passed and "membership" in report.failures
    assert report.membership_risk == pytest.approx(1.0)


def _saved(tmp_path):
    from tymi.profiling.profile_io import save_profile

    path = tmp_path / "p.yaml"
    save_profile(profile_dataset(_source(), sensitive_columns=["email"], salt=SALT), path)
    return path


def test_cli_quality_privacy_exports_and_gates(tmp_path) -> None:
    from typer.testing import CliRunner

    from tymi.cli.app import app

    out = tmp_path / "report.json"
    ok = CliRunner().invoke(
        app,
        [
            "report", "--quality-privacy", "-p", str(_saved(tmp_path)),
            "-n", "400", "--tolerance", "0.7", "-o", str(out),
        ],
    )
    assert ok.exit_code == 0, ok.stdout
    parsed = json.loads(out.read_text())
    assert parsed["quality_score"] >= 0.7 and parsed["membership_risk"] == 0.0

    # An impossible quality bar trips the CI gate → exit 1.
    strict = CliRunner().invoke(
        app,
        [
            "report", "--quality-privacy", "-p", str(_saved(tmp_path)),
            "-n", "400", "--tolerance", "1.0",
        ],
    )
    assert strict.exit_code == 1


def test_cli_report_rejects_both_flags(tmp_path) -> None:
    from typer.testing import CliRunner

    from tymi.cli.app import app

    result = CliRunner().invoke(
        app, ["report", "--fidelity", "--quality-privacy", "-p", str(_saved(tmp_path))]
    )
    assert result.exit_code == 2
    assert "exactly one" in result.stdout


def test_report_attribute_gate_trips_on_high_inference() -> None:
    n = 300
    x = np.linspace(0, 1, n)
    frame = pd.DataFrame({"secret": x, "qi": x * 2 + 0.01})  # secret inferable from qi
    schema = Schema(
        columns=(Column("secret", LogicalType.FLOAT), Column("qi", LogicalType.FLOAT))
    )
    ds = Dataset(frame=frame, schema=schema)
    profile = profile_dataset(ds, sensitive_columns=["secret"], salt=SALT)
    # Isolate the attribute gate: quality can't fail (tol 0), membership can't fail (thr 1).
    report = quality_privacy_report(
        profile, ds, tolerance=0.0, membership_threshold=1.0, attribute_threshold=0.5
    )
    assert not report.passed and "attribute_inference" in report.failures
    assert report.attribute_inference_risk is not None
    assert report.attribute_inference_risk > 0.5


def test_cli_privacy_gate_exit_1(tmp_path) -> None:
    from typer.testing import CliRunner

    from tymi.cli.app import app

    prof_path = _saved(tmp_path)  # profile of _source() with sensitive "email"
    leaky = tmp_path / "leaky.parquet"
    _source().frame.to_parquet(leaky)  # verbatim real rows → membership disclosure
    result = CliRunner().invoke(
        app,
        [
            "report", "--quality-privacy", "-p", str(prof_path),
            "--data", str(leaky), "--tolerance", "0.0", "--membership-threshold", "0.0",
        ],
    )
    assert result.exit_code == 1  # the membership CI gate trips through the CLI


def test_report_json_round_trips_and_is_deterministic() -> None:
    source = _source()
    profile = profile_dataset(source, sensitive_columns=["email"], salt=SALT)
    generated = generate_faithful(profile, rows=200, rng=make_rng(6))
    a = quality_privacy_report_to_json(quality_privacy_report(profile, generated))
    b = quality_privacy_report_to_json(quality_privacy_report(profile, generated))
    assert a == b  # deterministic
    parsed = json.loads(a)
    assert "quality_score" in parsed and "membership_risk" in parsed
    assert "attribute_inference_risk" in parsed and "fidelity" in parsed
