"""AC-6 (1.3): opt-in StarRocks connectivity.

StarRocks' ``allin1`` image is multi-GB and slow to become ready, so this test
is opt-in: set ``TYMI_TEST_STARROCKS=1`` to run it. StarRocks speaks the MySQL
wire protocol; its ``root`` user is passwordless by default, so we set a
password first (our adapter requires a non-empty credential), then verify the
adapter connects over the FE query port (9030).
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.integration

_OPT_IN = os.environ.get("TYMI_TEST_STARROCKS") == "1"


@pytest.mark.skipif(not _OPT_IN, reason="opt-in: set TYMI_TEST_STARROCKS=1 (heavy image)")
def test_connects_to_starrocks(monkeypatch: pytest.MonkeyPatch) -> None:
    docker = pytest.importorskip("docker")
    try:
        docker.from_env().ping()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Docker not available: {exc}")

    import pymysql
    from testcontainers.core.container import DockerContainer
    from testcontainers.core.waiting_utils import wait_for_logs

    from tymi.config.models import ConnectionConfig
    from tymi.engines.starrocks import StarRocksAdapter

    password = "Str0ng-P@ss!"
    container = DockerContainer("starrocks/allin1-ubuntu:latest").with_exposed_ports(9030)
    with container as sr:
        wait_for_logs(sr, "Enjoy the journey to StarRocks", timeout=300)
        host = sr.get_container_host_ip()
        port = int(sr.get_exposed_port(9030))
        # root starts passwordless; set a password so our adapter (which rejects
        # empty credentials) can connect.
        conn0 = pymysql.connect(host=host, port=port, user="root", password="")
        with conn0.cursor() as cur:
            cur.execute(f"SET PASSWORD FOR 'root' = PASSWORD('{password}')")
        conn0.close()

        monkeypatch.setenv("TYMI_DB_USER", "root")
        monkeypatch.setenv("TYMI_DB_PASSWORD", password)
        StarRocksAdapter(ConnectionConfig(host=host, port=port)).test_connection()
