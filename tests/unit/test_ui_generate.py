"""Story 5.3: faithful generation config + preview (UI)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tymi.domain.artifacts import Column, Dataset, LogicalType, Schema
from tymi.profiling.profiler import profile_dataset
from tymi.ui import services
from tymi.ui.launch import APP_PATH

_SCHEMA = Schema(
    columns=(
        Column("age", LogicalType.INTEGER),
        Column("score", LogicalType.FLOAT),
        Column("region", LogicalType.CATEGORICAL),
    )
)


def _profile():
    rng = np.random.default_rng(0)
    n = 400
    frame = pd.DataFrame(
        {
            "age": rng.integers(18, 70, n),
            "score": rng.normal(0, 1, n),
            "region": rng.choice(["LATAM", "EMEA", "APAC"], n),
        }
    )
    return profile_dataset(Dataset(frame=frame, schema=_SCHEMA))


# --- write-back to the shared Config (AC-4) ---------------------------------


def test_set_generation_persists_to_config() -> None:
    config = services.set_generation(
        services.default_config(), rows=500, seed=7, tolerance=0.8, conditions=("region=LATAM",)
    )
    assert config.generation.rows == 500
    assert config.generation.tolerance == 0.8
    assert config.generation.conditions == ["region=LATAM"]
    assert config.seed == 7


def test_set_generation_validates_and_rejects_bad_values() -> None:
    from pydantic import ValidationError

    # model_copy(update=) skips validators; set_generation must re-validate so it can't
    # persist a Config that fails its own schema (rows must be > 0, tolerance in [0,1]).
    with pytest.raises(ValidationError):
        services.set_generation(services.default_config(), rows=0, seed=0, tolerance=0.9)
    with pytest.raises(ValidationError):
        services.set_generation(services.default_config(), rows=10, seed=0, tolerance=5.0)


def test_generation_choices_round_trip_through_config_yaml(tmp_path) -> None:
    # AD-8: the persisted conditions survive a real YAML load (extra="forbid" accepts them).
    import yaml

    from tymi.config.loader import load_config

    config = services.set_generation(
        services.default_config(), rows=250, seed=3, tolerance=0.75, conditions=("age in [18,25]",)
    )
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config.model_dump(mode="json")), encoding="utf-8")
    loaded = load_config(path)
    assert loaded.generation.rows == 250
    assert loaded.generation.tolerance == 0.75
    assert loaded.generation.conditions == ["age in [18,25]"]
    assert loaded.seed == 3


# --- preview generation (AC-1, AC-3) ----------------------------------------


def test_preview_generates_rows_and_is_deterministic() -> None:
    profile = _profile()
    a = services.run_generation_preview(profile, rows=200, seed=1)
    b = services.run_generation_preview(profile, rows=200, seed=1)
    assert len(a.frame) == 200
    pd.testing.assert_frame_equal(a.frame, b.frame)  # AD-4: same seed → same sample


def test_preview_condition_is_satisfied_by_every_row() -> None:
    profile = _profile()
    out = services.run_generation_preview(profile, rows=150, seed=2, conditions=("region=LATAM",))
    assert (out.frame["region"] == "LATAM").all()


def test_preview_range_condition_is_satisfied_by_every_row() -> None:
    # The AC names the range form explicitly — prove it too, not just equality.
    profile = _profile()
    out = services.run_generation_preview(profile, rows=200, seed=5, conditions=("age in [18,25]",))
    ages = out.frame["age"].astype(int)
    assert (ages >= 18).all() and (ages <= 25).all()


def test_generation_comparison_excludes_datetime_and_text() -> None:
    # datetime/text columns are intentionally not compared (disclosed in the UI caption).
    schema = Schema(
        columns=(
            Column("score", LogicalType.FLOAT),
            Column("born", LogicalType.DATETIME),
            Column("note", LogicalType.STRING),
        )
    )
    rng = np.random.default_rng(0)
    frame = pd.DataFrame(
        {
            "score": rng.normal(0, 1, 100),
            "born": pd.to_datetime("2020-01-01") + pd.to_timedelta(rng.integers(0, 500, 100), "D"),
            "note": [f"t{i}" for i in range(100)],
        }
    )
    profile = profile_dataset(Dataset(frame=frame, schema=schema))
    generated = services.run_generation_preview(profile, rows=100, seed=1)
    names = {c.name for c in services.generation_comparison(profile, generated)}
    assert names == {"score"}  # datetime + text excluded


def test_preview_rejects_bad_rows_and_seed() -> None:
    profile = _profile()
    with pytest.raises(ValueError, match="rows must be > 0"):
        services.run_generation_preview(profile, rows=0)
    with pytest.raises(ValueError, match="seed must be >= 0"):
        services.run_generation_preview(profile, rows=10, seed=-1)


# --- source-vs-generated comparison (AC-2) ----------------------------------


def test_generation_comparison_aligns_source_and_generated() -> None:
    profile = _profile()
    generated = services.run_generation_preview(profile, rows=400, seed=3)
    charts = {c.name: c for c in services.generation_comparison(profile, generated)}
    assert set(charts) == {"age", "score", "region"}
    for chart in charts.values():
        assert list(chart.data.columns) == ["source", "generated"]
        # both distributions are probability vectors (sum ~1)
        assert chart.data["source"].sum() == pytest.approx(1.0, abs=1e-6)
        assert chart.data["generated"].sum() == pytest.approx(1.0, abs=1e-6)
    assert "LATAM" in charts["region"].data.index


def test_comparison_shows_out_of_range_generated_as_missing_mass() -> None:
    # A targeted condition beyond the source range (age∈[18,70]) puts all generated ages
    # outside the source bins; the generated series must show as missing mass (~0), not be
    # renormalized to 1 (which would misread as "generator produced nothing").
    profile = _profile()
    generated = services.run_generation_preview(
        profile, rows=200, seed=4, conditions=("age in [200,300]",)
    )
    charts = {c.name: c for c in services.generation_comparison(profile, generated)}
    assert charts["age"].data["source"].sum() == pytest.approx(1.0, abs=1e-6)
    assert charts["age"].data["generated"].sum() == pytest.approx(0.0, abs=1e-6)


# --- AppTest of the Generate page (AC-1..5) ---------------------------------


def _app_test():
    from streamlit.testing.v1 import AppTest

    return AppTest.from_file(str(Path(APP_PATH)))


def test_generate_page_no_profile_shows_guidance() -> None:
    at = _app_test().run()
    at.radio[0].set_value("Generate").run()
    assert not at.exception
    assert any("Profile a table first" in i.value for i in at.info)


def test_generate_page_previews_and_writes_back(monkeypatch) -> None:
    at = _app_test()
    at.session_state["profile"] = _profile()
    at.run()
    at.radio[0].set_value("Generate").run()
    at.number_input[0].set_value(120)  # rows
    at.number_input[1].set_value(9)  # seed
    at.slider[0].set_value(0.75)  # tolerance
    at.text_area[0].set_value("region=LATAM")
    at.button[0].click().run()  # Preview
    assert not at.exception
    assert "generated" in at.session_state
    assert len(at.session_state["generated"].frame) == 120
    assert (at.session_state["generated"].frame["region"] == "LATAM").all()
    assert any("Generated 120 rows" in s.value for s in at.success)
    # all choices written back to the shared Config (AD-8)
    written = at.session_state["config"]
    assert written.generation.rows == 120
    assert written.seed == 9
    assert written.generation.tolerance == 0.75
    assert written.generation.conditions == ["region=LATAM"]
    # sample + comparison charts rendered
    assert len(at.dataframe) >= 1
    assert any("Source vs generated" in s.value for s in at.subheader)
