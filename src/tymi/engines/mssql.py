"""MSSQL engine adapter (SQLAlchemy + pyodbc).

Connectivity only for now — ``introspect``/``sample``/``load`` arrive in later
stories (inherited from the base). MSSQL needs ODBC query params; everything
else (credentials, connection check, secret scrubbing) comes from the base.
"""

from __future__ import annotations

from tymi.engines._base import SqlAlchemyEngineAdapter

_DEFAULT_DRIVER = "ODBC Driver 18 for SQL Server"


class MssqlAdapter(SqlAlchemyEngineAdapter):
    """MSSQL over pyodbc / ODBC Driver 18."""

    DIALECT = "mssql+pyodbc"
    DEFAULT_PORT = 1433
    reproducible_sample = False  # NEWID() is random but not seed-reproducible

    def _sample_sql(self, table_quoted: str, rows: int, seed: int) -> tuple[list[str], str]:
        # MSSQL has no simple per-row seeded RNG; NEWID() is random but not
        # reproducible (documented limitation). TOP replaces LIMIT.
        return [], f"SELECT TOP ({rows}) * FROM {table_quoted} ORDER BY NEWID()"

    def _query(self) -> dict[str, str]:
        # Driver 18 encrypts by default; trust self-signed certs for test
        # containers (configurable). See ConnectionConfig.
        return {
            "driver": self._conn.driver or _DEFAULT_DRIVER,
            "Encrypt": "yes" if self._conn.encrypt else "no",
            "TrustServerCertificate": "yes" if self._conn.trust_server_certificate else "no",
        }
