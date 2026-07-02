"""AC-1..AC-6 (2.1): marginal distribution synthesis from a Profile (no DB)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from typer.testing import CliRunner

from tymi.cli.app import app
from tymi.core.rng import make_rng
from tymi.domain.artifacts import Column, Dataset, LogicalType, Schema
from tymi.profiling.profile_io import save_profile
from tymi.profiling.profiler import profile_dataset
from tymi.synth.marginals import MarginalSynthesizer, generate_marginals

runner = CliRunner()


def _source() -> Dataset:
    rng = np.random.default_rng(7)
    frame = pd.DataFrame(
        {
            "age": rng.integers(18, 80, size=400).astype(float),
            "score": rng.normal(50, 10, size=400),
            "gender": rng.choice(["M", "F"], size=400, p=[0.3, 0.7]),
            "created": pd.to_datetime("2021-01-01")
            + pd.to_timedelta(rng.integers(0, 365, size=400), unit="D"),
            "note": [f"free text value number {i} zzzzz" for i in range(400)],
        }
    )
    # inject some nulls into age
    frame.loc[frame.sample(frac=0.2, random_state=1).index, "age"] = None
    schema = Schema(
        columns=(
            Column("age", LogicalType.INTEGER),
            Column("score", LogicalType.FLOAT),
            Column("gender", LogicalType.CATEGORICAL),
            Column("created", LogicalType.DATETIME),
            Column("note", LogicalType.STRING),
        ),
        primary_key=("age",),
    )
    return Dataset(frame=frame, schema=schema)


def _profile():
    return profile_dataset(_source(), categorical_threshold=3)


def test_row_count_and_columns() -> None:
    ds = generate_marginals(_profile(), rows=250, rng=make_rng(0))
    assert len(ds.frame) == 250
    assert list(ds.frame.columns) == ["age", "score", "gender", "created", "note"]


def test_schema_is_preserved() -> None:
    profile = _profile()
    ds = generate_marginals(profile, rows=50, rng=make_rng(0))
    # AD-10: the produced Dataset carries the Profile's canonical Schema unchanged.
    assert ds.schema == profile.schema
    assert ds.schema.primary_key == ("age",)


def test_numeric_range_and_mean_within_tolerance() -> None:
    profile = _profile()
    ds = generate_marginals(profile, rows=5000, rng=make_rng(0))
    by = {c.name: c for c in profile.columns}
    score = ds.frame["score"].dropna()
    assert score.min() >= by["score"].numeric.min - 1e-9
    assert score.max() <= by["score"].numeric.max + 1e-9
    # mean should be close to the profiled mean (histogram inverse-transform)
    assert abs(score.mean() - by["score"].numeric.mean) < 2.0


def test_integer_column_is_whole_valued() -> None:
    ds = generate_marginals(_profile(), rows=500, rng=make_rng(0))
    age = ds.frame["age"].dropna()
    assert (age == age.round()).all()
    assert age.min() >= 18 and age.max() <= 79


def test_categorical_labels_subset_and_frequency() -> None:
    profile = _profile()
    ds = generate_marginals(profile, rows=5000, rng=make_rng(0))
    gender = ds.frame["gender"].dropna()
    assert set(gender.unique()) <= {"M", "F"}
    # ~70% F in the source; allow a reasonable tolerance
    assert 0.6 < (gender == "F").mean() < 0.8


def test_datetime_within_range() -> None:
    profile = _profile()
    ds = generate_marginals(profile, rows=2000, rng=make_rng(0))
    by = {c.name: c for c in profile.columns}
    created = ds.frame["created"].dropna()
    assert created.min() >= pd.Timestamp(by["created"].datetime.min)
    assert created.max() <= pd.Timestamp(by["created"].datetime.max)


def test_free_text_length_within_range_and_no_leak() -> None:
    profile = _profile()
    ds = generate_marginals(profile, rows=500, rng=make_rng(0))
    by = {c.name: c for c in profile.columns}
    lengths = ds.frame["note"].dropna().str.len()
    assert lengths.min() >= by["note"].text.min_length
    assert lengths.max() <= by["note"].text.max_length
    # AD-6: generated text is synthetic, never a raw source value
    assert "free text value number 0 zzzzz" not in set(ds.frame["note"])


def test_null_fraction_reproduced() -> None:
    profile = _profile()
    ds = generate_marginals(profile, rows=5000, rng=make_rng(0))
    # age had ~20% nulls in the source
    null_rate = ds.frame["age"].isna().mean()
    assert 0.15 < null_rate < 0.25


def test_all_null_column_stays_null() -> None:
    frame = pd.DataFrame({"empty": [None] * 5, "x": [1, 2, 3, 4, 5]})
    schema = Schema(
        columns=(Column("empty", LogicalType.STRING), Column("x", LogicalType.INTEGER))
    )
    profile = profile_dataset(Dataset(frame=frame, schema=schema))
    ds = generate_marginals(profile, rows=100, rng=make_rng(0))
    assert ds.frame["empty"].isna().all()
    assert ds.frame["x"].notna().all()


def test_same_seed_is_deterministic() -> None:
    profile = _profile()
    a = generate_marginals(profile, rows=300, rng=make_rng(42))
    b = generate_marginals(profile, rows=300, rng=make_rng(42))
    assert_frame_equal(a.frame, b.frame)


def test_different_seed_differs() -> None:
    profile = _profile()
    a = generate_marginals(profile, rows=300, rng=make_rng(1))
    b = generate_marginals(profile, rows=300, rng=make_rng(2))
    assert not a.frame.equals(b.frame)


def test_synthesizer_class_matches_function() -> None:
    profile = _profile()
    via_class = MarginalSynthesizer().generate(profile, rows=100, rng=make_rng(3))
    via_func = generate_marginals(profile, rows=100, rng=make_rng(3))
    assert_frame_equal(via_class.frame, via_func.frame)


def test_negative_rows_raises() -> None:
    with pytest.raises(ValueError, match="rows"):
        generate_marginals(_profile(), rows=-1, rng=make_rng(0))


def test_regenerating_profile_matches_marginals() -> None:
    # profile the generated data and check numeric marginals stay within tolerance
    profile = _profile()
    ds = generate_marginals(profile, rows=4000, rng=make_rng(0))
    regen = profile_dataset(ds, categorical_threshold=3)
    src = {c.name: c for c in profile.columns}
    gen = {c.name: c for c in regen.columns}
    assert abs(src["score"].numeric.mean - gen["score"].numeric.mean) < 2.0


def test_cli_generate_from_saved_profile(tmp_path: Path) -> None:
    profile = _profile()
    path = tmp_path / "p.yaml"
    save_profile(profile, path)
    result = runner.invoke(app, ["generate", "--profile", str(path), "--rows", "10", "--seed", "1"])
    assert result.exit_code == 0
    lines = [ln for ln in result.output.splitlines() if ln.strip()]
    assert lines[0].split(",") == ["age", "score", "gender", "created", "note"]
    assert len(lines) == 11  # header + 10 rows


def test_cli_generate_missing_profile_errors(tmp_path: Path) -> None:
    result = runner.invoke(app, ["generate", "--profile", str(tmp_path / "nope.yaml")])
    assert result.exit_code == 2  # typer rejects a non-existent --profile (exists=True)


def test_cli_generate_malformed_profile_errors(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("- not\n- a\n- mapping\n", encoding="utf-8")
    result = runner.invoke(app, ["generate", "--profile", str(path)])
    assert result.exit_code == 1
    assert "Could not load profile" in result.output


def test_cli_generate_invalid_datetime_content_errors(tmp_path: Path) -> None:
    # A Profile that loads fine but carries an unparsable datetime bound must
    # surface as a clean exit-1 message, not an uncaught traceback.
    profile = _profile()
    path = tmp_path / "p.yaml"
    save_profile(profile, path)
    text = path.read_text(encoding="utf-8").replace(
        "'2021-01-01T00:00:00'", "'not-a-real-date'"
    )
    # fall back to a broad replace if the exact quoting differs
    if "not-a-real-date" not in text:
        text = path.read_text(encoding="utf-8").replace("2021-01-01T00:00:00", "not-a-real-date")
    path.write_text(text, encoding="utf-8")
    result = runner.invoke(app, ["generate", "--profile", str(path)])
    assert result.exit_code == 1
    assert "Could not generate from profile" in result.output


def test_boolean_column_reproduced_as_booleans() -> None:
    frame = pd.DataFrame({"flag": [True, False, True, True, False, True]})
    schema = Schema(columns=(Column("flag", LogicalType.BOOLEAN),))
    profile = profile_dataset(Dataset(frame=frame, schema=schema))
    ds = generate_marginals(profile, rows=500, rng=make_rng(0))
    flag = ds.frame["flag"]
    # AD-10: a BOOLEAN column must come back as real booleans, not "True"/"False"
    assert flag.dtype == "boolean"
    assert set(flag.dropna().unique()) <= {True, False}
    # ~4/6 True in the source
    assert 0.5 < flag.mean() < 0.85


def test_numeric_histogram_shape_is_tracked() -> None:
    # a strongly skewed column: uniform sampling would fail this, inverse-transform
    # from the histogram must track the per-bin proportions.
    rng = np.random.default_rng(3)
    values = np.concatenate([rng.normal(0, 1, 4000), rng.normal(20, 1, 1000)])
    frame = pd.DataFrame({"x": values})
    schema = Schema(columns=(Column("x", LogicalType.FLOAT),))
    profile = profile_dataset(Dataset(frame=frame, schema=schema))
    stats = profile.columns[0].numeric
    ds = generate_marginals(profile, rows=20000, rng=make_rng(0))
    gen_counts, _ = np.histogram(ds.frame["x"].dropna(), bins=np.asarray(stats.histogram_bins))
    src_prop = np.asarray(stats.histogram_counts) / sum(stats.histogram_counts)
    gen_prop = gen_counts / gen_counts.sum()
    assert np.max(np.abs(src_prop - gen_prop)) < 0.05
