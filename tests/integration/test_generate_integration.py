"""AC-7 (2.1): profile a real PostgreSQL/MySQL table, then generate from it."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text

from tymi.core.rng import make_rng
from tymi.profiling.profiler import profile_dataset
from tymi.synth.marginals import generate_marginals

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


def _assert_generate(adapter: object) -> None:
    profile = profile_dataset(adapter.sample("people", rows=50, rng=make_rng(1)))
    dataset = generate_marginals(profile, rows=500, rng=make_rng(2))

    # AD-10: canonical Schema preserved.
    assert dataset.schema == profile.schema
    assert list(dataset.frame.columns) == profile.schema.names()
    assert len(dataset.frame) == 500

    by = {c.name: c for c in profile.columns}
    age = dataset.frame["age"].dropna()
    assert age.min() >= by["age"].numeric.min
    assert age.max() <= by["age"].numeric.max
    assert set(dataset.frame["gender"].dropna().unique()) <= {"M", "F"}

    # AD-4: same seed -> identical output.
    again = generate_marginals(profile, rows=500, rng=make_rng(2))
    assert dataset.frame.equals(again.frame)


def test_generate_postgres(monkeypatch: pytest.MonkeyPatch) -> None:
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
        _assert_generate(adapter)


def test_generate_mysql(monkeypatch: pytest.MonkeyPatch) -> None:
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
        _assert_generate(adapter)
