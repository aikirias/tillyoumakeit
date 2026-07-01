"""AC-7 (1.7): detect correlations on a real PostgreSQL/MySQL table.

Seeds a table where ``b = 2*a`` (perfect positive numeric correlation) and
``tier`` is a deterministic function of ``region`` (perfect categorical
dependence), then profiles and asserts the detected coefficients.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text

from tymi.core.rng import make_rng
from tymi.profiling.profiler import profile_dataset

pytestmark = pytest.mark.integration


def _row(i: int) -> str:
    region = "north" if i % 2 else "south"
    tier = "gold" if region == "north" else "silver"
    return f"({i}, {i}, {2 * i}, '{region}', '{tier}')"


_ROWS = ",".join(_row(i) for i in range(1, 51))
_DDL = [
    "CREATE TABLE metrics ("
    "  id INTEGER PRIMARY KEY, a INTEGER, b INTEGER,"
    "  region VARCHAR(10), tier VARCHAR(10)"
    ")",
    f"INSERT INTO metrics (id, a, b, region, tier) VALUES {_ROWS}",
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


def _assert_correlations(adapter: object) -> None:
    profile = profile_dataset(adapter.sample("metrics", rows=50, rng=make_rng(1)))
    corr = profile.correlations
    assert corr is not None

    num = corr.numeric
    assert num is not None
    a_i, b_i = num.columns.index("a"), num.columns.index("b")
    assert num.matrix[a_i][b_i] > 0.9  # b = 2*a => Spearman ~ 1.0

    cat = corr.categorical
    assert cat is not None
    r_i, t_i = cat.columns.index("region"), cat.columns.index("tier")
    assert cat.matrix[r_i][t_i] > 0.9  # tier determined by region => Cramer's V ~ 1.0


def test_correlations_postgres(monkeypatch: pytest.MonkeyPatch) -> None:
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
        _assert_correlations(adapter)


def test_correlations_mysql(monkeypatch: pytest.MonkeyPatch) -> None:
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
        _assert_correlations(adapter)
