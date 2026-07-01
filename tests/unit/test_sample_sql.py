"""AC-3/AC-4 (1.5): each adapter emits the right sampling SQL (no DB)."""

from __future__ import annotations

import pytest

from tymi.config.models import ConnectionConfig
from tymi.core.rng import make_rng
from tymi.engines.mssql import MssqlAdapter
from tymi.engines.mysql import MySqlAdapter
from tymi.engines.postgres import PostgresAdapter
from tymi.engines.starrocks import StarRocksAdapter


def _adapter(cls: type):
    return cls(ConnectionConfig(host="h"))


def test_postgres_uses_setseed_and_random() -> None:
    setup, query = _adapter(PostgresAdapter)._sample_sql('"t"', 10, 42)
    assert any("setseed" in s for s in setup)
    assert "ORDER BY random()" in query
    assert "LIMIT 10" in query


def test_mysql_uses_rand_seed() -> None:
    setup, query = _adapter(MySqlAdapter)._sample_sql("`t`", 10, 42)
    assert setup == []
    assert "RAND(42)" in query
    assert "LIMIT 10" in query


def test_starrocks_uses_rand_seed() -> None:
    _, query = _adapter(StarRocksAdapter)._sample_sql("`t`", 5, 7)
    assert "RAND(7)" in query
    assert "LIMIT 5" in query


def test_mssql_uses_top_and_newid() -> None:
    _, query = _adapter(MssqlAdapter)._sample_sql("[t]", 10, 42)
    assert "TOP (10)" in query
    assert "NEWID()" in query


def test_sample_rejects_nonpositive_rows() -> None:
    with pytest.raises(ValueError):
        _adapter(MySqlAdapter).sample("t", rows=0, rng=make_rng(0))


@pytest.mark.parametrize("bad_rows", ["10; DROP TABLE t", 10.5, True, None])
def test_sample_rejects_non_int_rows(bad_rows: object) -> None:
    # rows is interpolated into SQL; a non-int must be rejected before any DB work.
    with pytest.raises((ValueError, TypeError)):
        _adapter(MySqlAdapter).sample("t", rows=bad_rows, rng=make_rng(0))


def test_split_table_handles_schema_qualified() -> None:
    assert MySqlAdapter._split_table("t") == (None, "t")
    assert MySqlAdapter._split_table("s.t") == ("s", "t")


def test_reproducible_sample_flags() -> None:
    from tymi.engines.mssql import MssqlAdapter
    from tymi.engines.postgres import PostgresAdapter
    from tymi.engines.starrocks import StarRocksAdapter

    assert PostgresAdapter.reproducible_sample is True
    assert MySqlAdapter.reproducible_sample is True
    assert MssqlAdapter.reproducible_sample is False
    assert StarRocksAdapter.reproducible_sample is False
