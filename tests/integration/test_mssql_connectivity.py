"""AC-6: real connectivity against an MSSQL testcontainer.

Marked ``integration`` and excluded from the default run. Skips cleanly when
Docker (or the ODBC driver) is unavailable; a genuine connection failure when
Docker IS available will fail the test (in CI).
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


def test_connects_to_mssql_container(monkeypatch: pytest.MonkeyPatch) -> None:
    docker = pytest.importorskip("docker")
    pytest.importorskip("testcontainers.mssql")
    from testcontainers.mssql import SqlServerContainer

    from tymi.config.models import ConnectionConfig
    from tymi.engines.mssql import MssqlAdapter

    try:
        docker.from_env().ping()
    except Exception as exc:  # noqa: BLE001 - environment probe
        pytest.skip(f"Docker not available: {exc}")

    with SqlServerContainer("mcr.microsoft.com/mssql/server:2022-latest") as container:
        monkeypatch.setenv("TYMI_DB_USER", container.username)
        monkeypatch.setenv("TYMI_DB_PASSWORD", container.password)
        conn = ConnectionConfig(
            host=container.get_container_host_ip(),
            port=int(container.get_exposed_port(container.port)),
            database=container.dbname,
            trust_server_certificate=True,
        )
        # Raises EngineConnectionError on failure; success returns None.
        MssqlAdapter(conn).test_connection()
