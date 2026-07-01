"""AC-7 (1.6): profile a real PostgreSQL/MySQL table (sample + profile)."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text

from tymi.core.rng import make_rng
from tymi.profiling.profiler import profile_dataset

pytestmark = pytest.mark.integration

_ROWS = ",".join(
    f"({i}, {20 + i % 40}, '{'M' if i % 2 else 'F'}', DATE '2021-01-01', 'note {i}')"
    for i in range(1, 51)
)
_DDL = [
    "CREATE TABLE people ("
    "  id INTEGER PRIMARY KEY, age INTEGER, gender VARCHAR(1),"
    "  created DATE, note VARCHAR(200)"
    ")",
    f"INSERT INTO people (id, age, gender, created, note) VALUES {_ROWS}",
]


def _require_docker() -> None:
    docker = pytest.importorskip("docker")
    try:
        docker.from_env().ping()
    except Exception as exc:  # noqa: BLE001 - environment probe
        pytest.skip(f"Docker not available: {exc}")


def _seed(url: object) -> None:
    engine = create_engine(url)
    try:
        with engine.begin() as conn:
            for stmt in _DDL:
                conn.execute(text(stmt))
    finally:
        engine.dispose()


def _assert_profile(adapter: object) -> None:
    profile = profile_dataset(adapter.sample("people", rows=50, rng=make_rng(1)))
    assert profile.row_count == 50
    by = {c.name: c for c in profile.columns}
    assert by["age"].numeric is not None
    assert by["age"].numeric.min <= by["age"].numeric.max
    assert by["gender"].categories is not None
    assert {c.value for c in by["gender"].categories} <= {"M", "F"}
    assert by["created"].datetime is not None


def test_profile_postgres(monkeypatch: pytest.MonkeyPatch) -> None:
    _require_docker()
    from testcontainers.postgres import PostgresContainer

    from tymi.config.models import ConnectionConfig
    from tymi.engines.postgres import PostgresAdapter

    with PostgresContainer("postgres:16-alpine") as pg:
        monkeypatch.setenv("TYMI_DB_USER", pg.username)
        monkeypatch.setenv("TYMI_DB_PASSWORD", pg.password)
        adapter = PostgresAdapter(
            ConnectionConfig(
                host=pg.get_container_host_ip(),
                port=int(pg.get_exposed_port(pg.port)),
                database=pg.dbname,
            )
        )
        _seed(adapter.build_url())
        _assert_profile(adapter)


def test_profile_mysql(monkeypatch: pytest.MonkeyPatch) -> None:
    _require_docker()
    from testcontainers.mysql import MySqlContainer

    from tymi.config.models import ConnectionConfig
    from tymi.engines.mysql import MySqlAdapter

    with MySqlContainer("mysql:8.4") as my:
        monkeypatch.setenv("TYMI_DB_USER", my.username)
        monkeypatch.setenv("TYMI_DB_PASSWORD", my.password)
        adapter = MySqlAdapter(
            ConnectionConfig(
                host=my.get_container_host_ip(),
                port=int(my.get_exposed_port(my.port)),
                database=my.dbname,
            )
        )
        _seed(adapter.build_url())
        _assert_profile(adapter)
