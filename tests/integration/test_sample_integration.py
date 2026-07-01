"""AC-7 (1.5): real sampling against PostgreSQL and MySQL (count + reproducibility)."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text

from tymi.core.rng import make_rng

pytestmark = pytest.mark.integration


def _require_docker() -> None:
    docker = pytest.importorskip("docker")
    try:
        docker.from_env().ping()
    except Exception as exc:  # noqa: BLE001 - environment probe
        pytest.skip(f"Docker not available: {exc}")


def _seed_table(url: object) -> None:
    values = ",".join(f"({i},{i * 2})" for i in range(1, 101))
    engine = create_engine(url)
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE nums (id INTEGER PRIMARY KEY, val INTEGER)"))
            conn.execute(text(f"INSERT INTO nums (id, val) VALUES {values}"))
    finally:
        engine.dispose()


def _assert_sampling(adapter: object) -> None:
    ds1 = adapter.sample("nums", rows=10, rng=make_rng(42))
    assert len(ds1.frame) == 10
    assert ds1.schema.names() == ["id", "val"]
    assert list(ds1.frame.columns) == ["id", "val"]
    # seed-reproducible: same seed -> same rows in the same order
    ds2 = adapter.sample("nums", rows=10, rng=make_rng(42))
    assert list(ds1.frame["id"]) == list(ds2.frame["id"])


def test_sample_postgres(monkeypatch: pytest.MonkeyPatch) -> None:
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
        _seed_table(adapter.build_url())
        _assert_sampling(adapter)


def test_sample_mysql(monkeypatch: pytest.MonkeyPatch) -> None:
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
        _seed_table(adapter.build_url())
        _assert_sampling(adapter)
