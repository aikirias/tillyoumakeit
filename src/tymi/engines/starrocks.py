"""StarRocks engine adapter. Connectivity only.

StarRocks speaks the MySQL wire protocol, so this is a thin PyMySQL variant
pointed at the FE query port (default 9030).
"""

from __future__ import annotations

from tymi.engines._base import SqlAlchemyEngineAdapter


class StarRocksAdapter(SqlAlchemyEngineAdapter):
    DIALECT = "mysql+pymysql"
    DEFAULT_PORT = 9030
    # StarRocks runs queries distributed across BEs, so ORDER BY RAND(seed) is
    # not guaranteed reproducible (unlike single-node MySQL). Best-effort only.
    reproducible_sample = False

    def _sample_sql(self, table_quoted: str, rows: int, seed: int) -> tuple[list[str], str]:
        return [], f"SELECT * FROM {table_quoted} ORDER BY RAND({seed}) LIMIT {rows}"
