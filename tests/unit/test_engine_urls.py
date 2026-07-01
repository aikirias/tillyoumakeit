"""AC-4 (1.3): each adapter builds the right dialect + default port."""

from __future__ import annotations

import pytest

from tymi.config.models import ConnectionConfig
from tymi.engines.mysql import MySqlAdapter
from tymi.engines.postgres import PostgresAdapter
from tymi.engines.starrocks import StarRocksAdapter

CASES = [
    (PostgresAdapter, "postgresql+psycopg", 5432),
    (MySqlAdapter, "mysql+pymysql", 3306),
    (StarRocksAdapter, "mysql+pymysql", 9030),
]


@pytest.fixture(autouse=True)
def _creds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TYMI_DB_USER", "app")
    monkeypatch.setenv("TYMI_DB_PASSWORD", "p@ss!w0rd")


@pytest.mark.parametrize(("cls", "dialect", "default_port"), CASES)
def test_default_dialect_and_port(cls: type, dialect: str, default_port: int) -> None:
    url = cls(ConnectionConfig(host="db", database="app")).build_url()
    assert f"{url.get_backend_name()}+{url.get_driver_name()}" == dialect
    assert url.port == default_port
    assert url.host == "db"


@pytest.mark.parametrize(("cls", "dialect", "default_port"), CASES)
def test_explicit_port_overrides_default(cls: type, dialect: str, default_port: int) -> None:
    url = cls(ConnectionConfig(host="db", port=6000)).build_url()
    assert url.port == 6000


@pytest.mark.parametrize(("cls", "dialect", "default_port"), CASES)
def test_password_never_in_rendered_url(cls: type, dialect: str, default_port: int) -> None:
    url = cls(ConnectionConfig(host="db")).build_url()
    assert "p@ss!w0rd" not in url.render_as_string(hide_password=True)
