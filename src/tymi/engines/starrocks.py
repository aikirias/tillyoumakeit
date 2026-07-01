"""StarRocks engine adapter. Connectivity only.

StarRocks speaks the MySQL wire protocol, so this is a thin PyMySQL variant
pointed at the FE query port (default 9030).
"""

from __future__ import annotations

from tymi.engines._base import SqlAlchemyEngineAdapter


class StarRocksAdapter(SqlAlchemyEngineAdapter):
    DIALECT = "mysql+pymysql"
    DEFAULT_PORT = 9030
