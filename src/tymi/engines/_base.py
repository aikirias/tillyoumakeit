"""Shared base for SQLAlchemy-backed engine adapters.

Centralises credential resolution, the ``SELECT 1`` connectivity check, and
secret scrubbing so every engine adapter (MSSQL, PostgreSQL, MySQL, StarRocks)
only declares its dialect/default port and, if needed, extra URL query params.
Concrete drivers (pyodbc/psycopg/pymysql) are loaded lazily by SQLAlchemy at
connect time, so URL building stays unit-testable without system drivers.
"""

from __future__ import annotations

import os
import urllib.parse

import numpy as np
from sqlalchemy import URL, create_engine, text

from tymi.config.models import ConnectionConfig
from tymi.core.errors import EngineConnectionError, TableNotFoundError
from tymi.domain.artifacts import Dataset, Schema


class SqlAlchemyEngineAdapter:
    """Bidirectional engine adapter over SQLAlchemy (AD-2).

    Subclasses set ``DIALECT`` and ``DEFAULT_PORT`` and may override ``_query``.
    """

    DIALECT: str = ""
    DEFAULT_PORT: int = 0

    supports_introspect = True
    supports_sample = True
    supports_write = True

    #: Whether seeded sampling is deterministic on this engine. PostgreSQL and
    #: MySQL are; MSSQL (NEWID) and StarRocks (distributed RAND) are not.
    reproducible_sample = True

    def __init__(self, connection: ConnectionConfig) -> None:
        self._conn = connection

    # -- connectivity ---------------------------------------------------------

    def _port(self) -> int:
        port = self._conn.port or self.DEFAULT_PORT
        if not port:
            raise EngineConnectionError(
                f"No port for {self.DIALECT or type(self).__name__}: set 'port' in the config."
            )
        return port

    def _query(self) -> dict[str, str]:
        """Extra ODBC/driver query params. Empty by default."""
        return {}

    def _resolve_credentials(self) -> tuple[str, str]:
        user = os.environ.get(self._conn.user_env)
        if not user:
            raise EngineConnectionError(
                f"Username env var {self._conn.user_env!r} is not set or empty."
            )
        password = os.environ.get(self._conn.password_env)
        if not password:
            raise EngineConnectionError(
                f"Password env var {self._conn.password_env!r} is not set or empty."
            )
        return user, password

    def build_url(self) -> URL:
        """Build the SQLAlchemy URL (password handled by SQLAlchemy, not by us)."""
        user, password = self._resolve_credentials()
        return URL.create(
            self.DIALECT,
            username=user,
            password=password,
            host=self._conn.host,
            port=self._port(),
            database=self._conn.database,
            query=self._query(),
        )

    def test_connection(self) -> None:
        """Open a connection and run ``SELECT 1``; wrap+scrub any failure."""
        url = self.build_url()
        password = url.password or ""
        try:
            engine = create_engine(url)
            try:
                with engine.connect() as conn:
                    conn.execute(text("SELECT 1"))
            finally:
                engine.dispose()
        except Exception as exc:  # noqa: BLE001 - connection boundary must never leak the secret
            detail = _scrub(str(exc), password)
            raise EngineConnectionError(
                f"Cannot connect to {self.DIALECT} at {self._conn.host}:{self._port()}: {detail}"
            ) from None

    # -- read/write (later stories) ------------------------------------------

    @staticmethod
    def _split_table(table: str) -> tuple[str | None, str]:
        """Split ``schema.table`` into ``(schema, table)`` (``schema`` may be None)."""
        if "." in table:
            schema, name = table.rsplit(".", 1)
            return schema, name
        return None, table

    def introspect(self, table: str) -> Schema:
        """Reflect a table's schema (columns, types, PK, FK, unique, indexes)."""
        from tymi.engines._introspect import reflect_schema

        schema_name, table_name = self._split_table(table)
        url = self.build_url()
        password = url.password or ""
        try:
            engine = create_engine(url)
            try:
                return reflect_schema(engine, table_name, schema=schema_name)
            finally:
                engine.dispose()
        except TableNotFoundError:
            raise
        except Exception as exc:  # noqa: BLE001 - connection boundary must never leak the secret
            detail = _scrub(str(exc), password)
            raise EngineConnectionError(
                f"Cannot introspect {self.DIALECT} at {self._conn.host}:{self._port()}: {detail}"
            ) from None

    def _sample_sql(self, table_quoted: str, rows: int, seed: int) -> tuple[list[str], str]:
        """Return ``(setup_statements, query)`` for a random sample of ``rows``.

        Every engine must implement this — there is no safe generic default
        (a plain ``LIMIT`` would be non-random and silently ignore the seed).
        """
        raise NotImplementedError(f"{type(self).__name__} must implement _sample_sql.")

    def sample(self, table: str, *, rows: int, rng: np.random.Generator) -> Dataset:
        """Return up to ``rows`` randomly-sampled rows as a canonical Dataset."""
        import pandas as pd

        # rows is interpolated into SQL, so it must be a genuine positive int
        # (the public library API can be called with anything, unlike the CLI).
        if isinstance(rows, bool) or not isinstance(rows, int) or rows <= 0:
            raise ValueError("rows must be a positive integer.")
        schema = self.introspect(table)  # validates existence + gives the Schema
        seed = int(rng.integers(0, 2**31 - 1))
        url = self.build_url()
        password = url.password or ""
        try:
            engine = create_engine(url)
            try:
                schema_name, table_name = self._split_table(table)
                preparer = engine.dialect.identifier_preparer
                table_quoted = preparer.quote(table_name)
                if schema_name:
                    table_quoted = f"{preparer.quote_schema(schema_name)}.{table_quoted}"
                setup, query = self._sample_sql(table_quoted, rows, seed)
                with engine.connect() as conn:
                    for statement in setup:
                        conn.execute(text(statement))
                    frame = pd.read_sql(text(query), conn)
            finally:
                engine.dispose()
        except TableNotFoundError:
            raise
        except Exception as exc:  # noqa: BLE001 - connection boundary must never leak the secret
            detail = _scrub(str(exc), password)
            raise EngineConnectionError(
                f"Cannot sample {self.DIALECT} at {self._conn.host}:{self._port()}: {detail}"
            ) from None
        return Dataset(frame=frame, schema=schema)

    def load(self, dataset: Dataset, *, table: str) -> None:
        raise NotImplementedError("Loading is delivered in Epic 2.")


def _scrub(message: str, secret: str) -> str:
    """Remove a secret from a message, including URL-encoded forms (NFR-6)."""
    if not secret:
        return message
    for variant in {secret, urllib.parse.quote(secret, safe=""), urllib.parse.quote_plus(secret)}:
        message = message.replace(variant, "***")
    return message
