"""Story 5.5: reports view + export (UI)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tymi.domain.artifacts import (
    Column,
    Dataset,
    FaultManifest,
    LogicalType,
    Schema,
    fidelity_report_to_json,
    quality_privacy_report_to_json,
)
from tymi.eval.fidelity import fidelity_report
from tymi.eval.privacy_report import quality_privacy_report
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


def _generated(profile):
    return services.run_generation_preview(profile, rows=200, seed=1)


# --- faithful reports = the CLI artifacts (AC-1, AC-4) ----------------------


def test_faithful_reports_match_cli_functions() -> None:
    profile = _profile()
    generated = _generated(profile)
    fidelity, privacy = services.faithful_reports(profile, generated, tolerance=0.8)
    assert fidelity_report_to_json(fidelity) == fidelity_report_to_json(
        fidelity_report(profile, generated, tolerance=0.8)
    )
    assert quality_privacy_report_to_json(privacy) == quality_privacy_report_to_json(
        quality_privacy_report(profile, generated, tolerance=0.8)
    )


# --- manifest table (AC-1) --------------------------------------------------


def test_manifest_table_from_entries_and_empty() -> None:
    manifest = FaultManifest(
        entries=[{"mutator": "outlier", "row": 3, "column": "age", "fault_type": "numeric_outlier"}]
    )
    df = services.manifest_table(manifest)
    assert list(df["column"]) == ["age"] and df.iloc[0]["row"] == 3
    empty = services.manifest_table(FaultManifest())
    assert empty.empty and "fault_type" in empty.columns


def test_manifest_table_keeps_row_as_integer_on_ragged_entries() -> None:
    # Structural mutators omit "row"; the column must stay integer (Int64) not float "3.0".
    manifest = FaultManifest(
        entries=[
            {"mutator": "outlier", "row": 3, "column": "age", "fault_type": "numeric_outlier"},
            {"mutator": "renamed_column", "column": "age", "fault_type": "rename"},
        ]
    )
    df = services.manifest_table(manifest)
    assert str(df["row"].dtype) == "Int64"
    assert df["row"].iloc[0] == 3 and pd.isna(df["row"].iloc[1])


# --- export bytes = CLI exporter (AC-2, AC-4) -------------------------------


def test_export_bytes_matches_cli_exporter(tmp_path) -> None:
    from tymi.io.exporters import get_exporter

    profile = _profile()
    generated = _generated(profile)
    for fmt in services.EXPORT_FORMATS:
        target = tmp_path / f"cli.{fmt}"
        get_exporter(fmt).export(generated, target=str(target))
        assert services.export_bytes(generated, fmt) == target.read_bytes()


def test_export_bytes_rejects_unknown_format() -> None:
    from tymi.core.errors import ExportError

    profile = _profile()
    with pytest.raises(ExportError):
        services.export_bytes(_generated(profile), "xlsx")


# --- load into engine (AC-3) ------------------------------------------------


class _LoadAdapter:
    calls: list[tuple[str, int]] = []

    def __init__(self, connection) -> None:
        self.connection = connection

    def load(self, dataset, *, table: str) -> None:
        type(self).calls.append((table, len(dataset.frame)))


def test_load_to_engine_calls_adapter_load() -> None:
    _LoadAdapter.calls = []
    config = services.set_connection(services.default_config(), engine="postgres", host="h")
    profile = _profile()
    msg = services.load_to_engine(
        config, _generated(profile), table="out", engines={"postgres": _LoadAdapter}
    )
    assert _LoadAdapter.calls == [("out", 200)]
    assert "Loaded 200 rows into 'out'" in msg


def test_load_to_engine_requires_connection_and_table() -> None:
    profile = _profile()
    dataset = _generated(profile)
    with pytest.raises(ValueError, match="No connection configured"):
        services.load_to_engine(services.default_config(), dataset, table="t")
    config = services.set_connection(services.default_config(), engine="postgres", host="h")
    with pytest.raises(ValueError, match="Destination table is required"):
        services.load_to_engine(config, dataset, table="  ", engines={"postgres": _LoadAdapter})


# --- AppTest of the Reports page (AC-1, AC-5) -------------------------------


def _app_test():
    from streamlit.testing.v1 import AppTest

    return AppTest.from_file(str(Path(APP_PATH)))


def test_reports_page_guidance_when_nothing_generated() -> None:
    at = _app_test().run()
    at.radio[0].set_value("Reports").run()
    assert not at.exception
    assert any("Generate faithful data or run a chaos" in i.value for i in at.info)


def test_reports_page_shows_faithful_reports() -> None:
    profile = _profile()
    at = _app_test()
    at.session_state["profile"] = profile
    at.session_state["generated"] = _generated(profile)
    at.run()
    at.radio[0].set_value("Reports").run()
    assert not at.exception
    subheaders = [s.value for s in at.subheader]
    assert "Fidelity report" in subheaders and "Quality & privacy report" in subheaders
    assert "Export" in subheaders
    assert len(at.json) >= 2  # both report payloads rendered
    # export controls render without error (download_button has no AppTest accessor; the
    # format selectbox and no-exception confirm export_bytes succeeded)
    assert any(s.key == "export_fmt" for s in at.selectbox)


def test_reports_page_shows_chaos_manifest() -> None:
    profile = _profile()
    chaotic, manifest = services.run_chaos_preview(
        profile, rows=100, seed=1, mode="mixed", rate=0.5, mutators=("outlier",)
    )
    at = _app_test()
    at.session_state["profile"] = profile
    at.session_state["chaotic"] = chaotic
    at.session_state["manifest"] = manifest
    at.run()
    at.radio[0].set_value("Reports").run()
    assert not at.exception
    assert any("Fault Manifest" in s.value for s in at.subheader)
    assert len(at.dataframe) >= 1  # manifest table rendered
    assert any("Export" in s.value for s in at.subheader)  # export section for the chaotic data


def test_reports_page_toggle_when_both_runs_present() -> None:
    profile = _profile()
    generated = _generated(profile)
    chaotic, manifest = services.run_chaos_preview(
        profile, rows=100, seed=1, mode="mixed", rate=0.5, mutators=("outlier",)
    )
    at = _app_test()
    at.session_state["profile"] = profile
    at.session_state["generated"] = generated
    at.session_state["chaotic"] = chaotic
    at.session_state["manifest"] = manifest
    at.run()
    at.radio(key="wizard_step").set_value("Reports").run()  # navigate via the sidebar
    # default shows Faithful (first option) → faithful reports reachable, not shadowed
    assert any("Fidelity report" in s.value for s in at.subheader)
    # switch the report toggle to Chaos
    at.radio(key="report_mode").set_value("Chaos").run()
    assert any("Fault Manifest" in s.value for s in at.subheader)
