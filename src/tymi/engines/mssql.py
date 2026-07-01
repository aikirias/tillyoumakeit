"""MSSQL engine adapter (first concrete ``EngineAdapter``).

Connectivity only for Story 1.2 — ``introspect``/``sample``/``load`` arrive in
later stories. ``pyodbc`` is intentionally **not** imported here: SQLAlchemy
loads it lazily when a connection is actually opened, so URL-building and
redaction are unit-testable without the ODBC driver installed (AD-2, AD-3).
"""

from __future__ import annotations

import os

import numpy as np
from sqlalchemy import URL, create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from tymi.config.models import ConnectionConfig
from tymi.core.errors import EngineConnectionError
from tymi.domain.artifacts import Dataset, Schema

_DRIVER_DIALECT = "mssql+pyodbc"


class MssqlAdapter:
    """Bidirectional MSSQL adapter (AD-2). Capabilities all supported."""

    supports_introspect = True
    supports_sample = True
    supports_write = True

    def __init__(self, connection: ConnectionConfig) -> None:
        self._conn = connection

    # -- connectivity ---------------------------------------------------------

    def _resolve_credentials(self) -> tuple[str, str]:
        """Read username/password from the configured env vars.

        Raises ``EngineConnectionError`` naming the missing variable (never its
        value) so the failure is actionable without leaking secrets.
        """
        try:
            user = os.environ[self._conn.user_env]
        except KeyError:
            raise EngineConnectionError(
                f"MSSQL username env var {self._conn.user_env!r} is not set."
            ) from None
        try:
            password = os.environ[self._conn.password_env]
        except KeyError:
            raise EngineConnectionError(
                f"MSSQL password env var {self._conn.password_env!r} is not set."
            ) from None
        return user, password

    def build_url(self) -> URL:
        """Build the SQLAlchemy connection URL (password handled by SQLAlchemy)."""
        user, password = self._resolve_credentials()
        query = {
            "driver": self._conn.driver,
            "Encrypt": "yes" if self._conn.encrypt else "no",
            "TrustServerCertificate": "yes" if self._conn.trust_server_certificate else "no",
        }
        return URL.create(
            _DRIVER_DIALECT,
            username=user,
            password=password,
            host=self._conn.host,
            port=self._conn.port,
            database=self._conn.database,
            query=query,
        )

    def test_connection(self) -> None:
        """Open a connection and run ``SELECT 1``.

        Wraps any driver/SQLAlchemy error in ``EngineConnectionError`` with the
        secret scrubbed from the message.
        """
        url = self.build_url()
        password = url.password or ""
        try:
            engine = create_engine(url)
            try:
                with engine.connect() as conn:
                    conn.execute(text("SELECT 1"))
            finally:
                engine.dispose()
        except (SQLAlchemyError, ImportError, OSError) as exc:
            detail = _scrub(str(exc), password)
            raise EngineConnectionError(
                f"Cannot connect to MSSQL at {self._conn.host}:{self._conn.port}: {detail}"
            ) from None

    # -- read/write (later stories) ------------------------------------------

    def introspect(self, table: str) -> Schema:
        raise NotImplementedError("Schema introspection is delivered in Story 1.4.")

    def sample(self, table: str, *, rows: int, rng: np.random.Generator) -> Dataset:
        raise NotImplementedError("Sampling is delivered in Story 1.5.")

    def load(self, dataset: Dataset, *, table: str) -> None:
        raise NotImplementedError("Loading is delivered in Epic 2.")


def _scrub(message: str, secret: str) -> str:
    """Remove a secret substring from a message (defence-in-depth for logs)."""
    return message.replace(secret, "***") if secret else message
