"""Story 5.1: Streamlit app shell + connection management."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from tymi.core.errors import EngineConnectionError
from tymi.ui import services
from tymi.ui.launch import APP_PATH, build_ui_command

# --- fake engine adapters (no DB) -------------------------------------------


class _OkAdapter:
    supports_introspect = True
    supports_sample = True
    supports_write = True

    def __init__(self, connection) -> None:
        self.connection = connection

    def test_connection(self) -> None:  # succeeds
        return None


class _FailAdapter:
    def __init__(self, connection) -> None:
        self.connection = connection

    def test_connection(self) -> None:
        raise EngineConnectionError("host unreachable")


# --- services: set / summarise connection (AC-3, AC-4) ----------------------


def test_set_connection_stores_engine_and_env_names_only() -> None:
    config = services.set_connection(
        services.default_config(),
        engine="postgres",
        host="db.internal",
        port=5432,
        database="app",
        user_env="MY_USER",
        password_env="MY_PASS",
    )
    assert config.source.engine == "postgres"
    assert config.source.connection.host == "db.internal"
    assert config.source.connection.port == 5432
    # NFR-6: only env-var names are stored, never a raw secret.
    summary = services.connection_summary(config)
    assert summary["user_env"] == "MY_USER" and summary["password_env"] == "MY_PASS"
    blob = repr(config.source.connection)
    assert "MY_USER" in blob  # the name is fine
    # no field named like a plaintext credential value exists on the model
    assert not hasattr(config.source.connection, "password")
    assert not hasattr(config.source.connection, "user")


def test_set_connection_rejects_unknown_engine() -> None:
    with pytest.raises(ValueError, match="unknown engine"):
        services.set_connection(services.default_config(), engine="oracle", host="h")


def test_set_connection_rejects_bad_port() -> None:
    from tymi.core.errors import TymiError

    with pytest.raises((ValueError, TymiError)):
        services.set_connection(
            services.default_config(), engine="mysql", host="h", port=99999
        )


def test_connection_summary_none_before_configured() -> None:
    assert services.connection_summary(services.default_config()) is None


def test_set_connection_rejects_blank_host() -> None:
    for bad in ("", "   "):
        with pytest.raises(ValueError, match="host must not be empty"):
            services.set_connection(services.default_config(), engine="mssql", host=bad)


def test_set_connection_normalises_blank_optionals() -> None:
    config = services.set_connection(
        services.default_config(),
        engine="postgres",
        host="  db  ",
        database="",
        user_env="",
        password_env="  ",
    )
    conn = config.source.connection
    assert conn.host == "db"  # stripped
    assert conn.database is None  # blank → None
    assert conn.user_env == "TYMI_DB_USER" and conn.password_env == "TYMI_DB_PASSWORD"


# --- services: test connection via injected registry (AC-2) -----------------


def test_test_connection_success_with_fake_adapter() -> None:
    config = services.set_connection(services.default_config(), engine="mssql", host="h")
    result = services.test_connection(config, engines={"mssql": _OkAdapter})
    assert result.ok and "OK" in result.message


def test_test_connection_reports_failure_without_secrets() -> None:
    config = services.set_connection(services.default_config(), engine="mssql", host="h")
    result = services.test_connection(config, engines={"mssql": _FailAdapter})
    assert not result.ok and "unreachable" in result.message


def test_test_connection_misbehaving_adapter_no_leak() -> None:
    # A 3rd-party adapter that raises a non-Tymi error must not crash the UI nor echo a
    # raw driver traceback (which could carry a DSN/password) — a generic message only.
    class _BadAdapter:
        def __init__(self, connection) -> None:
            raise RuntimeError("dsn=postgres://user:secretpw@host/db")

    config = services.set_connection(services.default_config(), engine="postgres", host="h")
    result = services.test_connection(config, engines={"postgres": _BadAdapter})
    assert not result.ok
    assert "secretpw" not in result.message and "unexpected adapter error" in result.message


def test_test_connection_unconfigured_and_unknown_engine() -> None:
    assert not services.test_connection(services.default_config(), engines={}).ok
    config = services.set_connection(services.default_config(), engine="mysql", host="h")
    res = services.test_connection(config, engines={})  # engine not registered
    assert not res.ok and "Unknown engine" in res.message


# --- launcher (AC-1) --------------------------------------------------------


def test_build_ui_command_shape() -> None:
    cmd = build_ui_command(port=9002)
    assert cmd[0] == sys.executable
    assert cmd[1:5] == ["-m", "streamlit", "run", str(APP_PATH)]
    assert cmd[-2:] == ["--server.port", "9002"]
    assert APP_PATH.name == "app.py" and APP_PATH.exists()


def test_cli_ui_command_registered() -> None:
    from typer.testing import CliRunner

    from tymi.cli.app import app

    result = CliRunner().invoke(app, ["ui", "--help"])
    assert result.exit_code == 0
    assert "Streamlit" in result.stdout


# --- AppTest smoke of the shell + connection page (AC-2, AC-5) --------------


def _app_test():
    from streamlit.testing.v1 import AppTest

    return AppTest.from_file(str(Path(APP_PATH)))


def test_app_shell_renders_connection_by_default() -> None:
    at = _app_test().run()
    assert not at.exception
    assert any("TYMI" in t.value for t in at.title)
    assert any("Connection" in h.value for h in at.header)
    # NFR-6 caption present
    assert any("names" in c.value for c in at.caption)


def test_app_sidebar_navigates_to_placeholder_steps() -> None:
    at = _app_test().run()
    at.radio[0].set_value("Profile").run()
    assert not at.exception
    assert any("Story 5.2" in i.value for i in at.info)


def test_app_saves_connection_through_the_form() -> None:
    at = _app_test().run()
    at.selectbox[0].set_value("postgres")
    # widgets have no explicit keys → drive by position: host, database, user_env, password_env
    at.text_input[0].set_value("db.internal")
    at.number_input[0].set_value(5432)
    at.button[0].click().run()  # "Save connection"
    assert not at.exception
    assert any("Saved connection" in s.value for s in at.success)
    assert at.session_state["config"].source.engine == "postgres"


def test_app_all_placeholder_steps_render() -> None:
    for step in ("Profile", "Generate", "Chaos", "Reports"):
        at = _app_test().run()
        at.radio[0].set_value(step).run()
        assert not at.exception
        assert any("Story 5." in i.value for i in at.info)


def test_app_test_connection_button_uses_injected_registry(monkeypatch) -> None:
    # Drive the "Test connection" button end-to-end with a fake registry (no DB).
    monkeypatch.setattr(services, "load_engines", lambda: {"postgres": _OkAdapter})
    at = _app_test().run()
    at.selectbox[0].set_value("postgres")
    at.text_input[0].set_value("db.internal")
    at.button[0].click().run()  # Save connection (form submit)
    at.button(key="test_conn").click().run()  # Test connection
    assert not at.exception
    assert any("OK" in s.value for s in at.success)


def test_ui_built_config_round_trips_through_load_config(tmp_path) -> None:
    # AD-8: a UI-built Config is the same artifact the CLI loads from YAML.
    from tymi.config.loader import load_config
    from tymi.domain.artifacts import profile_to_json  # noqa: F401  (ensures pkg import ok)

    config = services.set_connection(
        services.default_config(), engine="mysql", host="h", port=3306, database="app"
    )
    import yaml

    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config.model_dump(mode="json")), encoding="utf-8")
    loaded = load_config(path)
    assert loaded.source.engine == "mysql"
    assert loaded.source.connection.port == 3306
    assert loaded.source.connection.user_env == "TYMI_DB_USER"
