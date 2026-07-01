"""PostgreSQL engine adapter (SQLAlchemy + psycopg v3). Connectivity only."""

from __future__ import annotations

from tymi.engines._base import SqlAlchemyEngineAdapter


class PostgresAdapter(SqlAlchemyEngineAdapter):
    DIALECT = "postgresql+psycopg"
    DEFAULT_PORT = 5432

    def _sample_sql(self, table_quoted: str, rows: int, seed: int) -> tuple[list[str], str]:
        # setseed makes the following random() reproducible within the session;
        # disabling parallel gather keeps the seeded RNG stable (parallel workers
        # can otherwise reset it).
        seed_float = (seed % 1_000_000) / 1_000_000
        return (
            ["SET max_parallel_workers_per_gather = 0", f"SELECT setseed({seed_float})"],
            f"SELECT * FROM {table_quoted} ORDER BY random() LIMIT {rows}",
        )
