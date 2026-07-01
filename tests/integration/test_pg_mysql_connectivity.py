"""AC-6 (1.3): real connectivity for PostgreSQL and MySQL via testcontainers.

Marked ``integration`` and excluded from the default run. Skips cleanly when
Docker is unavailable; a genuine connection failure fails the test.
psycopg/pymysql are pure wheels, so no system driver is needed.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


def _require_docker() -> None:
    docker = pytest.importorskip("docker")
    try:
        docker.from_env().ping()
    except Exception as exc:  # noqa: BLE001 - environment probe
        pytest.skip(f"Docker not available: {exc}")


def test_connects_to_postgres(monkeypatch: pytest.MonkeyPatch) -> None:
    _require_docker()
    from testcontainers.postgres import PostgresContainer

    from tymi.config.models import ConnectionConfig
    from tymi.engines.postgres import PostgresAdapter

    with PostgresContainer("postgres:16-alpine") as pg:
        monkeypatch.setenv("TYMI_DB_USER", pg.username)
        monkeypatch.setenv("TYMI_DB_PASSWORD", pg.password)
        conn = ConnectionConfig(
            host=pg.get_container_host_ip(),
            port=int(pg.get_exposed_port(pg.port)),
            database=pg.dbname,
        )
        PostgresAdapter(conn).test_connection()


def test_connects_to_mysql(monkeypatch: pytest.MonkeyPatch) -> None:
    _require_docker()
    from testcontainers.mysql import MySqlContainer

    from tymi.config.models import ConnectionConfig
    from tymi.engines.mysql import MySqlAdapter

    with MySqlContainer("mysql:8.4") as my:
        monkeypatch.setenv("TYMI_DB_USER", my.username)
        monkeypatch.setenv("TYMI_DB_PASSWORD", my.password)
        conn = ConnectionConfig(
            host=my.get_container_host_ip(),
            port=int(my.get_exposed_port(my.port)),
            database=my.dbname,
        )
        MySqlAdapter(conn).test_connection()
