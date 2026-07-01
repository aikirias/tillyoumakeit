"""AC-2: the MSSQL adapter is discovered via the tymi.engines entry point."""

from __future__ import annotations

from tymi.config.models import ConnectionConfig
from tymi.core.plugins import load_engines
from tymi.engines.mssql import MssqlAdapter
from tymi.ports import EngineAdapter


def test_mssql_registered_under_entry_point() -> None:
    engines = load_engines()
    assert engines.get("mssql") is MssqlAdapter


def test_mssql_satisfies_engine_adapter_protocol() -> None:
    adapter = MssqlAdapter(ConnectionConfig(host="localhost"))
    assert isinstance(adapter, EngineAdapter)
    assert adapter.supports_introspect
    assert adapter.supports_sample
    assert adapter.supports_write
