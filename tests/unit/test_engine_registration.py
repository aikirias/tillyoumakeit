"""AC-3 (1.2) / AC-3 (1.3): all engine adapters discovered via entry points."""

from __future__ import annotations

import pytest

from tymi.config.models import ConnectionConfig
from tymi.core.plugins import load_engines
from tymi.engines.mssql import MssqlAdapter
from tymi.engines.mysql import MySqlAdapter
from tymi.engines.postgres import PostgresAdapter
from tymi.engines.starrocks import StarRocksAdapter
from tymi.ports import EngineAdapter

_EXPECTED = {
    "mssql": MssqlAdapter,
    "postgres": PostgresAdapter,
    "mysql": MySqlAdapter,
    "starrocks": StarRocksAdapter,
}


def test_all_engines_registered() -> None:
    engines = load_engines()
    for name, cls in _EXPECTED.items():
        assert engines.get(name) is cls


@pytest.mark.parametrize("cls", list(_EXPECTED.values()))
def test_adapter_satisfies_protocol(cls: type) -> None:
    adapter = cls(ConnectionConfig(host="localhost"))
    assert isinstance(adapter, EngineAdapter)
    assert adapter.supports_introspect
    assert adapter.supports_sample
    assert adapter.supports_write
