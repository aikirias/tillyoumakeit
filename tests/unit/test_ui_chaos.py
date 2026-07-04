"""Story 5.4: chaos policy config + preview (UI)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tymi.core.errors import ChaosError
from tymi.domain.artifacts import Column, Dataset, ForeignKey, LogicalType, Schema
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
    n = 300
    frame = pd.DataFrame(
        {
            "age": rng.integers(18, 70, n),
            "score": rng.normal(0, 1, n),
            "region": rng.choice(["LATAM", "EMEA", "APAC"], n),
        }
    )
    return profile_dataset(Dataset(frame=frame, schema=_SCHEMA))


def _fk_profile():
    schema = Schema(
        columns=(Column("id", LogicalType.INTEGER), Column("parent_id", LogicalType.INTEGER)),
        foreign_keys=(ForeignKey(("parent_id",), "parents", ("id",)),),
    )
    frame = pd.DataFrame({"id": range(50), "parent_id": range(50)})
    return profile_dataset(Dataset(frame=frame, schema=schema))


# --- mutator discovery + confirmation gate (AC-3) ---------------------------


def test_available_mutators_includes_registered() -> None:
    names = services.available_mutators()
    assert "outlier" in names and names == sorted(names)


def test_requires_confirmation_only_for_fully_chaotic_with_fks() -> None:
    assert services.requires_confirmation(_fk_profile(), "fully_chaotic") is True
    assert services.requires_confirmation(_fk_profile(), "mixed") is False
    assert services.requires_confirmation(_profile(), "fully_chaotic") is False  # no FKs


def test_fully_chaotic_with_fks_refused_without_confirmation() -> None:
    profile = _fk_profile()
    with pytest.raises(ChaosError, match="referential integrity"):
        services.run_chaos_preview(profile, mode="fully_chaotic", mutators=("outlier",))
    # ...and the gate does not fire in mixed mode.
    services.run_chaos_preview(profile, rows=20, mode="mixed", mutators=("outlier",))


def test_fully_chaotic_with_fks_allowed_when_confirmed() -> None:
    # The affirmative half of the gate: confirmation lets the fully-chaotic run proceed.
    profile = _fk_profile()
    chaotic, manifest = services.run_chaos_preview(
        profile, rows=30, seed=1, mode="fully_chaotic", mutators=("outlier",), confirmed=True
    )
    assert len(chaotic.frame) == 30
    assert len(manifest.entries) > 0


# --- preview + manifest (AC-1, AC-2) ----------------------------------------


def test_preview_injects_faults_and_is_deterministic() -> None:
    profile = _profile()
    chaotic_a, manifest_a = services.run_chaos_preview(
        profile, rows=200, seed=1, mode="mixed", rate=0.5, mutators=("outlier",)
    )
    chaotic_b, manifest_b = services.run_chaos_preview(
        profile, rows=200, seed=1, mode="mixed", rate=0.5, mutators=("outlier",)
    )
    assert len(manifest_a.entries) > 0
    assert manifest_a.entries == manifest_b.entries  # AD-4: same seed → same manifest
    pd.testing.assert_frame_equal(chaotic_a.frame, chaotic_b.frame)


def test_fault_locations_match_manifest_and_columns() -> None:
    profile = _profile()
    _chaotic, manifest = services.run_chaos_preview(
        profile, rows=200, seed=2, mode="mixed", rate=0.4, mutators=("outlier",)
    )
    locs = services.fault_locations(manifest)
    assert locs  # non-empty
    # outlier only targets numeric columns
    assert {c for _, c in locs} <= {"age", "score"}
    # every location corresponds to a manifest entry
    manifest_cells = {(int(e["row"]), e["column"]) for e in manifest.entries}
    assert locs == manifest_cells


def test_fault_style_frame_marks_only_corrupted_cells() -> None:
    profile = _profile()
    chaotic, manifest = services.run_chaos_preview(
        profile, rows=50, seed=7, mode="mixed", rate=0.5, mutators=("outlier",)
    )
    head = chaotic.frame.head(20)
    styles = services.fault_style_frame(head, manifest)
    assert styles.shape == head.shape
    marked = {(r, c) for r in styles.index for c in styles.columns if styles.loc[r, c]}
    expected = {(r, c) for (r, c) in services.fault_locations(manifest) if r in set(head.index)}
    assert marked == expected
    # every cell is either unstyled ("") or the fault style
    cells = [styles.loc[r, c] for r in styles.index for c in styles.columns]
    assert all(v in ("", services.FAULT_STYLE) for v in cells)


def test_preview_rejects_bad_rows_and_seed() -> None:
    profile = _profile()
    with pytest.raises(ValueError, match="rows must be > 0"):
        services.run_chaos_preview(profile, rows=0)
    with pytest.raises(ValueError, match="seed must be >= 0"):
        services.run_chaos_preview(profile, rows=10, seed=-1)


# --- write-back to Config (AC-4) --------------------------------------------


def test_set_chaos_persists_and_round_trips(tmp_path) -> None:
    import yaml

    from tymi.config.loader import load_config

    config = services.set_chaos(
        services.default_config(), mode="fully_chaotic", rate=0.6, mutators=("outlier",)
    )
    assert config.chaos.mode == "fully_chaotic"
    assert config.chaos.rate == 0.6
    assert [m.name for m in config.chaos.mutators] == ["outlier"]
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config.model_dump(mode="json")), encoding="utf-8")
    loaded = load_config(path)
    assert loaded.chaos.mode == "fully_chaotic"
    assert loaded.chaos.rate == 0.6
    assert [m.name for m in loaded.chaos.mutators] == ["outlier"]


def test_set_chaos_rejects_bad_mode() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        services.set_chaos(services.default_config(), mode="nonsense", rate=0.1, mutators=())


# --- AppTest of the Chaos page (AC-1..5) ------------------------------------


def _app_test():
    from streamlit.testing.v1 import AppTest

    return AppTest.from_file(str(Path(APP_PATH)))


def test_chaos_page_no_profile_shows_guidance() -> None:
    at = _app_test().run()
    at.radio[0].set_value("Chaos").run()
    assert not at.exception
    assert any("Profile a table first" in i.value for i in at.info)


def test_chaos_page_previews_and_writes_back() -> None:
    at = _app_test()
    at.session_state["profile"] = _profile()
    at.run()
    at.radio[0].set_value("Chaos").run()
    at.slider[0].set_value(0.5)  # rate
    at.multiselect[0].set_value(["outlier"])
    at.button[0].click().run()  # Preview
    assert not at.exception
    assert "chaotic" in at.session_state and "manifest" in at.session_state
    assert any("Injected" in s.value for s in at.success)
    # policy written back to the shared Config (AD-8)
    written = at.session_state["config"].chaos
    assert written.rate == 0.5
    assert [m.name for m in written.mutators] == ["outlier"]
    assert len(at.dataframe) >= 1  # highlighted sample rendered


def test_chaos_page_mode_prefills_from_config() -> None:
    at = _app_test()
    at.session_state["profile"] = _profile()
    at.session_state["config"] = services.set_chaos(
        services.default_config(), mode="fully_chaotic", rate=0.3, mutators=("outlier",)
    )
    at.run()
    at.radio[0].set_value("Chaos").run()
    assert at.selectbox[0].value == "fully_chaotic"  # mode round-trips into the form


def test_chaos_re_preview_uses_changed_mutators() -> None:
    # Regression: a second preview with a DIFFERENT mutator selection must run the new
    # selection, not silently re-run the previously written-back policy (needs stable keys).
    at = _app_test()
    at.session_state["profile"] = _profile()
    at.run()
    at.radio[0].set_value("Chaos").run()
    at.multiselect[0].set_value(["outlier"])
    at.slider[0].set_value(0.5)
    at.button[0].click().run()  # preview 1
    assert {e["mutator"] for e in at.session_state["manifest"].entries} == {"outlier"}

    at.multiselect[0].set_value(["text_in_numeric"])
    at.button[0].click().run()  # preview 2 with the changed selection
    assert not at.exception
    assert {e["mutator"] for e in at.session_state["manifest"].entries} == {"text_in_numeric"}
    assert [m.name for m in at.session_state["config"].chaos.mutators] == ["text_in_numeric"]


def test_chaos_page_fully_chaotic_confirmation_flow_through_ui() -> None:
    at = _app_test()
    at.session_state["profile"] = _fk_profile()
    at.run()
    at.radio[0].set_value("Chaos").run()
    at.selectbox[0].set_value("fully_chaotic")
    at.multiselect[0].set_value(["outlier"])
    at.number_input[0].set_value(30)  # rows
    at.button[0].click().run()  # Preview WITHOUT ticking confirm → refused
    assert not at.exception
    assert any("referential integrity" in e.value for e in at.error)
    assert "chaotic" not in at.session_state  # no preview, no write-back

    # Now tick the confirmation checkbox and preview again → proceeds.
    at.selectbox[0].set_value("fully_chaotic")
    at.multiselect[0].set_value(["outlier"])
    at.number_input[0].set_value(30)
    at.checkbox[0].set_value(True)
    at.button[0].click().run()
    assert not at.exception
    assert "chaotic" in at.session_state
    assert any("Injected" in s.value for s in at.success)
