"""AC-4/AC-5: MSSQL URL building, env-var credentials, and password redaction."""

from __future__ import annotations

import urllib.parse

import pytest

from tymi.config.models import ConnectionConfig
from tymi.core.errors import EngineConnectionError
from tymi.engines._base import _scrub
from tymi.engines.mssql import MssqlAdapter

PASSWORD = "s3cr3t-P@ss!"


def _adapter(**kwargs: object) -> MssqlAdapter:
    return MssqlAdapter(ConnectionConfig(host="db.example.com", database="app", **kwargs))


def _with_creds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TYMI_DB_USER", "sa")
    monkeypatch.setenv("TYMI_DB_PASSWORD", PASSWORD)


def test_build_url_has_driver_and_trust(monkeypatch: pytest.MonkeyPatch) -> None:
    _with_creds(monkeypatch)
    url = _adapter().build_url()
    assert url.query["driver"] == "ODBC Driver 18 for SQL Server"
    assert url.query["TrustServerCertificate"] == "yes"
    assert url.query["Encrypt"] == "yes"
    assert url.host == "db.example.com"
    assert url.port == 1433
    assert url.get_backend_name() == "mssql"


def test_encrypt_and_trust_toggle_off(monkeypatch: pytest.MonkeyPatch) -> None:
    _with_creds(monkeypatch)
    url = _adapter(encrypt=False, trust_server_certificate=False).build_url()
    assert url.query["Encrypt"] == "no"
    assert url.query["TrustServerCertificate"] == "no"


def test_missing_password_env_raises_naming_the_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TYMI_DB_USER", "sa")
    monkeypatch.delenv("TYMI_DB_PASSWORD", raising=False)
    with pytest.raises(EngineConnectionError) as excinfo:
        _adapter().build_url()
    assert "TYMI_DB_PASSWORD" in str(excinfo.value)


def test_missing_user_env_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TYMI_DB_USER", raising=False)
    monkeypatch.setenv("TYMI_DB_PASSWORD", PASSWORD)
    with pytest.raises(EngineConnectionError):
        _adapter().build_url()


def test_password_is_redacted_in_rendered_url(monkeypatch: pytest.MonkeyPatch) -> None:
    _with_creds(monkeypatch)
    url = _adapter().build_url()
    rendered = url.render_as_string(hide_password=True)
    assert PASSWORD not in rendered
    assert "***" in rendered


def test_both_env_vars_missing_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TYMI_DB_USER", raising=False)
    monkeypatch.delenv("TYMI_DB_PASSWORD", raising=False)
    with pytest.raises(EngineConnectionError):
        _adapter().build_url()


def test_empty_password_env_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TYMI_DB_USER", "sa")
    monkeypatch.setenv("TYMI_DB_PASSWORD", "")
    with pytest.raises(EngineConnectionError) as excinfo:
        _adapter().build_url()
    assert "empty" in str(excinfo.value).lower()


def test_scrub_removes_raw_and_encoded_forms() -> None:
    secret = "p@ss/w:rd?#"
    encoded = urllib.parse.quote(secret, safe="")
    plus = urllib.parse.quote_plus(secret)
    scrubbed = _scrub(f"raw={secret} enc={encoded} plus={plus}", secret)
    assert secret not in scrubbed
    assert encoded not in scrubbed
    assert plus not in scrubbed


def test_connection_error_is_wrapped_and_scrubbed(monkeypatch: pytest.MonkeyPatch) -> None:
    _with_creds(monkeypatch)
    encoded = urllib.parse.quote(PASSWORD, safe="")

    def _boom(url: object):
        raise RuntimeError(f"driver failed pwd={PASSWORD} enc={encoded}")

    monkeypatch.setattr("tymi.engines._base.create_engine", _boom)
    with pytest.raises(EngineConnectionError) as excinfo:
        _adapter().test_connection()
    message = str(excinfo.value)
    assert PASSWORD not in message
    assert encoded not in message
    assert "db.example.com:1433" in message
