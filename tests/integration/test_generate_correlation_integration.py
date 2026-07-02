"""AC-7 (2.2): profile a real PG/MySQL table with correlated numeric columns,
generate via the Gaussian copula, and assert the correlation is preserved."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text

from tymi.core.rng import make_rng
from tymi.profiling.profiler import profile_dataset
from tymi.synth.generator import DEFAULT_CORRELATION_TOLERANCE, generate_faithful

pytestmark = pytest.mark.integration

# b = 2*a (strong positive), c = 300 - 2*a (strong negative)
_ROWS = ",".join(f"({i}, {i}, {2 * i}, {300 - 2 * i})" for i in range(1, 101))
_DDL = [
    "CREATE TABLE metrics (id INTEGER PRIMARY KEY, a INTEGER, b INTEGER, c INTEGER)",
    f"INSERT INTO metrics (id, a, b, c) VALUES {_ROWS}",
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


def _assert_correlation_preserved(adapter: object) -> None:
    profile = profile_dataset(adapter.sample("metrics", rows=100, rng=make_rng(1)))
    dataset = generate_faithful(profile, rows=4000, rng=make_rng(2))

    assert dataset.schema == profile.schema
    gen = dataset.frame[["a", "b", "c"]].corr(method="spearman")
    src = profile.correlations.numeric
    names = list(src.columns)
    for i, x in enumerate(names):
        for j, y in enumerate(names):
            if i < j and x in ("a", "b", "c") and y in ("a", "b", "c"):
                assert abs(src.matrix[i][j] - gen.loc[x, y]) < DEFAULT_CORRELATION_TOLERANCE

    # sanity: the strong relations survive with the right sign
    assert gen.loc["a", "b"] > 0.85
    assert gen.loc["a", "c"] < -0.85

    # determinism: same seed -> identical output
    again = generate_faithful(profile, rows=4000, rng=make_rng(2))
    assert dataset.frame.equals(again.frame)


def test_correlation_postgres(monkeypatch: pytest.MonkeyPatch) -> None:
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
        _assert_correlation_preserved(adapter)


def test_correlation_mysql(monkeypatch: pytest.MonkeyPatch) -> None:
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
        _assert_correlation_preserved(adapter)
