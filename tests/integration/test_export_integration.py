"""AC-3 (2.6): load a generated Dataset into a real PostgreSQL/MySQL table.

The Dataset is built offline (source-independent), loaded via ``EngineAdapter.load``
into a fresh destination table created from the canonical Schema (AR-10), then read
back to confirm every row and the Schema-driven column types landed.
"""

from __future__ import annotations

import pandas as pd
import pytest
from sqlalchemy import create_engine

from tymi.domain.artifacts import Column, Dataset, LogicalType, Schema

pytestmark = pytest.mark.integration


def _dataset() -> Dataset:
    frame = pd.DataFrame(
        {
            "id": pd.array([1, 2, 3], dtype="Int64"),
            "amount": [10.5, 20.0, 30.25],
            "active": [True, False, True],
            "created": pd.to_datetime(["2021-01-01", "2021-06-15", "2022-03-03"]),
            "label": ["ada", "grace", "linus"],
        }
    )
    schema = Schema(
        columns=(
            Column("id", LogicalType.INTEGER),
            Column("amount", LogicalType.FLOAT),
            Column("active", LogicalType.BOOLEAN),
            Column("created", LogicalType.DATETIME),
            Column("label", LogicalType.STRING),
        )
    )
    return Dataset(frame=frame, schema=schema)


def _require_docker() -> None:
    docker = pytest.importorskip("docker")
    try:
        docker.from_env().ping()
    except Exception as exc:  # noqa: BLE001 - environment probe
        pytest.skip(f"Docker not available: {exc}")


def _assert_load_roundtrip(adapter: object) -> None:
    adapter.load(_dataset(), table="synthetic")
    back = pd.read_sql_table("synthetic", create_engine(adapter.build_url()))
    assert len(back) == 3
    assert set(back.columns) == {"id", "amount", "active", "created", "label"}
    assert sorted(back["id"].astype(int).tolist()) == [1, 2, 3]
    assert sorted(back["label"].tolist()) == ["ada", "grace", "linus"]
    assert pd.api.types.is_datetime64_any_dtype(pd.to_datetime(back["created"]))


def test_load_postgres(monkeypatch: pytest.MonkeyPatch) -> None:
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
        _assert_load_roundtrip(adapter)


def test_load_mysql(monkeypatch: pytest.MonkeyPatch) -> None:
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
        _assert_load_roundtrip(adapter)
