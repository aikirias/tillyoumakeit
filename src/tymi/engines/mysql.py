"""MySQL engine adapter (SQLAlchemy + PyMySQL). Connectivity only."""

from __future__ import annotations

from tymi.engines._base import SqlAlchemyEngineAdapter


class MySqlAdapter(SqlAlchemyEngineAdapter):
    DIALECT = "mysql+pymysql"
    DEFAULT_PORT = 3306

    def _sample_sql(self, table_quoted: str, rows: int, seed: int) -> tuple[list[str], str]:
        # RAND(seed) makes the ordering reproducible.
        return [], f"SELECT * FROM {table_quoted} ORDER BY RAND({seed}) LIMIT {rows}"
