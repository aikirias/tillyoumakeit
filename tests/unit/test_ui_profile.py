"""Story 5.2: profile & schema explorer (UI)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from tymi.domain.artifacts import Column, Dataset, LogicalType, Schema, profile_to_json
from tymi.profiling.profiler import profile_dataset
from tymi.ui import services
from tymi.ui.launch import APP_PATH

_SCHEMA = Schema(
    columns=(
        Column("age", LogicalType.INTEGER),
        Column("score", LogicalType.FLOAT),
        Column("region", LogicalType.CATEGORICAL),
        Column("born", LogicalType.DATETIME),
        Column("note", LogicalType.STRING),
    )
)


def _sample_frame() -> pd.DataFrame:
    rng = np.random.default_rng(0)
    n = 200
    return pd.DataFrame(
        {
            "age": rng.integers(18, 70, n),
            "score": rng.normal(0, 1, n),
            "region": rng.choice(["LATAM", "EMEA", "APAC"], n),
            "born": pd.to_datetime("2020-01-01") + pd.to_timedelta(rng.integers(0, 3650, n), "D"),
            "note": [f"free text {i}" for i in range(n)],  # high-cardinality → text stats
        }
    )


class _FakeAdapter:
    supports_introspect = True
    supports_sample = True
    supports_write = True

    def __init__(self, connection) -> None:
        self.connection = connection

    def sample(self, table: str, *, rows: int, rng) -> Dataset:
        return Dataset(frame=_sample_frame(), schema=_SCHEMA)


def _connected_config() -> services.Config:
    return services.set_connection(services.default_config(), engine="postgres", host="h")


# --- run_profile: same artifact as the CLI (AC-1, AC-4) ---------------------


def test_run_profile_matches_profile_dataset() -> None:
    config = _connected_config()
    profile = services.run_profile(config, "t", engines={"postgres": _FakeAdapter})
    expected = profile_dataset(
        Dataset(frame=_sample_frame(), schema=_SCHEMA),
        sensitive_columns=[],
        not_sensitive_columns=[],
        classify_pii=False,
    )
    assert profile_to_json(profile) == profile_to_json(expected)


def test_run_profile_sensitive_merge_and_pii_match_cli_wiring() -> None:
    # Exercise the branching wiring (non-empty sensitive merge + classify_pii) so the
    # CLI-parity claim isn't only proven on the trivial path.
    config = services.set_connection(
        services.default_config(), engine="postgres", host="h"
    )
    config = config.model_copy(
        update={"source": config.source.model_copy(update={"sensitive_columns": ["region"]})}
    )
    profile = services.run_profile(
        config,
        "t",
        extra_sensitive=("note",),
        classify_pii=True,
        engines={"postgres": _FakeAdapter},
    )
    # The merge (extra ∪ config, order-preserving) reached profile_dataset → both columns
    # are hashed into the leakage guard, and their raw stats are suppressed (AD-6).
    assert profile.leakage_guard is not None
    assert set(profile.leakage_guard.columns) == {"note", "region"}
    suppressed = {cp.name: cp for cp in profile.columns}
    assert suppressed["region"].categories is None  # sensitive categorical → labels suppressed


def test_run_profile_round_trips_through_save_load(tmp_path) -> None:
    from tymi.profiling.profile_io import load_profile, save_profile

    config = _connected_config()
    profile = services.run_profile(config, "t", engines={"postgres": _FakeAdapter})
    path = tmp_path / "p.yaml"
    save_profile(profile, path)
    assert profile_to_json(load_profile(path)) == profile_to_json(profile)


def test_run_profile_requires_connection_and_table() -> None:
    import pytest

    with pytest.raises(ValueError, match="No connection configured"):
        services.run_profile(services.default_config(), "t")
    with pytest.raises(ValueError, match="Table name is required"):
        services.run_profile(_connected_config(), "  ", engines={"postgres": _FakeAdapter})
    with pytest.raises(ValueError, match="seed must be >= 0"):
        services.run_profile(_connected_config(), "t", seed=-1, engines={"postgres": _FakeAdapter})


def test_histogram_labels_stay_unique_on_large_magnitude() -> None:
    # Narrow bins on a huge value collapse to identical value strings; the builder must
    # fall back to bin indices so bars don't merge/mislead.
    schema = Schema(columns=(Column("v", LogicalType.FLOAT),))
    frame = pd.DataFrame({"v": np.linspace(1e6, 1e6 + 0.02, 60)})
    profile = profile_dataset(Dataset(frame=frame, schema=schema))
    chart = services.profile_charts(profile)[0]
    assert chart.kind == "histogram"
    assert len(set(chart.data.index)) == len(chart.data.index)  # unique labels


# --- schema table + distribution charts (AC-2, AC-3) ------------------------


def test_schema_table_columns() -> None:
    df = services.schema_table(_SCHEMA)
    assert list(df["column"]) == ["age", "score", "region", "born", "note"]
    assert set(df.columns) == {"column", "type", "nullable", "primary_key"}


def _profile() -> object:
    return profile_dataset(Dataset(frame=_sample_frame(), schema=_SCHEMA))


def test_profile_charts_cover_every_column_kind() -> None:
    charts = {c.name: c for c in services.profile_charts(_profile())}
    assert charts["age"].kind == "histogram" and charts["age"].data is not None
    assert charts["score"].kind == "histogram"
    assert charts["region"].kind == "categories" and "LATAM" in charts["region"].data.index
    born = charts["born"]
    assert born.kind == "datetime"
    assert born.data is not None  # day-of-week frequency
    assert born.extra is not None  # month frequency (AC-3)
    assert charts["note"].kind == "text" and charts["note"].data is None
    assert charts["age"].summary["count"] == 200


# --- AppTest: profile page renders schema + charts (AC-1..5) ----------------


def _app_test():
    from streamlit.testing.v1 import AppTest

    return AppTest.from_file(str(Path(APP_PATH)))


def test_profile_page_no_connection_shows_guidance() -> None:
    at = _app_test().run()
    at.radio[0].set_value("Profile").run()
    assert not at.exception
    assert any("Configure a connection first" in i.value for i in at.info)


def test_profile_page_profiles_and_renders(monkeypatch) -> None:
    monkeypatch.setattr(services, "load_engines", lambda: {"postgres": _FakeAdapter})
    at = _app_test()
    at.session_state["config"] = _connected_config()
    at.run()
    at.radio[0].set_value("Profile").run()
    at.text_input[0].set_value("customers")
    at.button[0].click().run()  # Profile submit
    assert not at.exception
    assert "profile" in at.session_state
    assert any("Profiled" in s.value for s in at.success)
    assert len(at.dataframe) >= 1  # schema table rendered
    # distribution section renders per column (bar_chart has no AppTest accessor, so assert
    # the surrounding markdown/caption the chart loop emits for every column).
    assert any("Distributions" in s.value for s in at.subheader)
    assert any("**age**" in m.value for m in at.markdown)
    assert len(at.caption) >= 5  # one summary caption per profiled column


def test_profile_page_failure_does_not_leak_secret_or_keep_stale(monkeypatch) -> None:
    # A misbehaving adapter whose error embeds a DSN must not be echoed, and a failed
    # re-profile must clear the previously shown profile.
    class _LeakyAdapter:
        def __init__(self, connection) -> None:
            self.connection = connection
            self._calls = 0

        def sample(self, table: str, *, rows: int, rng) -> Dataset:
            self._calls += 1
            if table == "ok":
                return Dataset(frame=_sample_frame(), schema=_SCHEMA)
            raise RuntimeError("FATAL: password=SuperSecretPw host=10.0.0.5")

    monkeypatch.setattr(services, "load_engines", lambda: {"postgres": _LeakyAdapter})
    at = _app_test()
    at.session_state["config"] = _connected_config()
    at.run()
    at.radio[0].set_value("Profile").run()
    at.text_input[0].set_value("ok")
    at.button[0].click().run()  # succeeds → profile stored
    assert "profile" in at.session_state
    at.text_input[0].set_value("bad")
    at.button[0].click().run()  # fails
    assert not at.exception
    assert "profile" not in at.session_state  # stale profile cleared
    assert not any("SuperSecretPw" in e.value for e in at.error)  # no secret leak
    assert any("unexpected adapter error" in e.value for e in at.error)
