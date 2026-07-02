"""AC-7 (2.3): profile real related PG/MySQL tables, then generate them
referentially-consistently (parents before children, valid FKs, unique PKs)."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text

from tymi.core.rng import make_rng
from tymi.profiling.profiler import profile_dataset
from tymi.synth.relational import generate_related

pytestmark = pytest.mark.integration

_CUSTOMERS = ",".join(f"({i}, 'c{i}@shop.com')" for i in range(1, 41))
_ORDERS = ",".join(f"({i}, {1 + (i % 40)}, {i * 1.5})" for i in range(1, 121))
_DDL = [
    "CREATE TABLE customers (id INTEGER PRIMARY KEY, email VARCHAR(120))",
    "CREATE TABLE orders ("
    "  id INTEGER PRIMARY KEY, customer_id INTEGER, amount DECIMAL(10,2),"
    "  FOREIGN KEY (customer_id) REFERENCES customers(id)"
    ")",
    f"INSERT INTO customers (id, email) VALUES {_CUSTOMERS}",
    f"INSERT INTO orders (id, customer_id, amount) VALUES {_ORDERS}",
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


def _assert_relational(adapter: object) -> None:
    customers = profile_dataset(adapter.sample("customers", rows=40, rng=make_rng(1)))
    orders = profile_dataset(adapter.sample("orders", rows=120, rng=make_rng(1)))
    # orders' Schema must carry the FK to customers (reflected on introspect)
    assert any(fk.referred_table == "customers" for fk in orders.schema.foreign_keys)

    out = generate_related(
        {"orders": orders, "customers": customers},  # child-first input on purpose
        rows={"customers": 40, "orders": 300},
        rng=make_rng(2),
    )
    cust, ords = out["customers"].frame, out["orders"].frame

    assert cust["id"].is_unique  # AC-2
    assert ords["id"].is_unique
    assert set(ords["customer_id"]).issubset(set(cust["id"]))  # AC-1: valid FKs
    assert cust["email"].is_unique  # AC-3 (unique constraint / synthetic emails)
    assert all("@" in v for v in cust["email"])  # AC-4: realistic values
    assert "c1@shop.com" not in set(cust["email"])  # AC-5: no source value copied


def test_relational_postgres(monkeypatch: pytest.MonkeyPatch) -> None:
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
        _assert_relational(adapter)


def test_relational_mysql(monkeypatch: pytest.MonkeyPatch) -> None:
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
        _assert_relational(adapter)
