"""MySQL engine adapter (SQLAlchemy + PyMySQL). Connectivity only."""

from __future__ import annotations

from tymi.engines._base import SqlAlchemyEngineAdapter


class MySqlAdapter(SqlAlchemyEngineAdapter):
    DIALECT = "mysql+pymysql"
    DEFAULT_PORT = 3306
