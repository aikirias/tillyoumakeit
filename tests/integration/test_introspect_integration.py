"""AC-6 (1.4): real schema introspection against PostgreSQL and MySQL."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text

from tymi.core.errors import TableNotFoundError
from tymi.domain.artifacts import LogicalType

pytestmark = pytest.mark.integration

_DDL = [
    "CREATE TABLE parent (id INTEGER PRIMARY KEY, name VARCHAR(50) NOT NULL)",
    # Table-level FK so it is honored by both PostgreSQL and MySQL/InnoDB
    # (MySQL silently ignores an inline column-level REFERENCES clause).
    "CREATE TABLE child ("
    "  id INTEGER PRIMARY KEY,"
    "  parent_id INTEGER,"
    "  amount DECIMAL(10,2),"
    "  code VARCHAR(20),"
    "  UNIQUE (code),"
    "  FOREIGN KEY (parent_id) REFERENCES parent(id)"
    ")",
    "CREATE INDEX ix_child_amount ON child (amount)",
]


def _require_docker() -> None:
    docker = pytest.importorskip("docker")
    try:
        docker.from_env().ping()
    except Exception as exc:  # noqa: BLE001 - environment probe
        pytest.skip(f"Docker not available: {exc}")


def _run_ddl(url: object, statements: list[str]) -> None:
    engine = create_engine(url)
    try:
        with engine.begin() as conn:
            for stmt in statements:
                conn.execute(text(stmt))
    finally:
        engine.dispose()


def _assert_child_schema(adapter: object) -> None:
    schema = adapter.introspect("child")
    assert schema.names() == ["id", "parent_id", "amount", "code"]
    assert schema.primary_key == ("id",)
    assert len(schema.foreign_keys) == 1
    fk = schema.foreign_keys[0]
    assert fk.referred_table == "parent"
    assert fk.columns == ("parent_id",)
    assert fk.referred_columns == ("id",)
    types = {c.name: c.logical_type for c in schema.columns}
    assert types["id"] == LogicalType.INTEGER
    assert types["amount"] == LogicalType.FLOAT
    assert ("code",) in schema.unique_constraints
    assert any(ix.name == "ix_child_amount" for ix in schema.indexes)
    # missing table surfaces a typed error
    with pytest.raises(TableNotFoundError):
        adapter.introspect("no_such_table")


def test_introspect_postgres(monkeypatch: pytest.MonkeyPatch) -> None:
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
        _run_ddl(adapter.build_url(), _DDL)
        _assert_child_schema(adapter)


def test_introspect_mysql(monkeypatch: pytest.MonkeyPatch) -> None:
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
        _run_ddl(adapter.build_url(), _DDL)
        _assert_child_schema(adapter)
