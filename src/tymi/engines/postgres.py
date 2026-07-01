"""PostgreSQL engine adapter (SQLAlchemy + psycopg v3). Connectivity only."""

from __future__ import annotations

from tymi.engines._base import SqlAlchemyEngineAdapter


class PostgresAdapter(SqlAlchemyEngineAdapter):
    DIALECT = "postgresql+psycopg"
    DEFAULT_PORT = 5432
