"""Engine-agnostic schema reflection via SQLAlchemy.

SQLAlchemy's Inspector is dialect-agnostic, so one implementation covers all
four engines. Maps reflected metadata onto the canonical domain ``Schema``.
"""

from __future__ import annotations

from sqlalchemy import Engine
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import types as satypes
from sqlalchemy.exc import NoSuchTableError

from tymi.core.errors import TableNotFoundError
from tymi.domain.artifacts import Column, ForeignKey, Index, LogicalType, Schema


def _qualified(schema: str | None, table: str) -> str:
    return f"{schema}.{table}" if schema else table


def map_logical_type(sa_type: object) -> LogicalType:
    """Map a SQLAlchemy column type to a canonical LogicalType."""
    if isinstance(sa_type, satypes.Boolean):
        return LogicalType.BOOLEAN
    if isinstance(sa_type, satypes.Integer):
        return LogicalType.INTEGER
    if isinstance(sa_type, (satypes.Numeric, satypes.Float)):
        return LogicalType.FLOAT
    if isinstance(sa_type, (satypes.Date, satypes.DateTime, satypes.Time)):
        return LogicalType.DATETIME
    if isinstance(sa_type, satypes.Enum):
        return LogicalType.CATEGORICAL
    return LogicalType.STRING


def _safe(call, default):  # noqa: ANN001, ANN201 - tiny local helper
    """Run a reflection call, returning ``default`` if the dialect can't."""
    try:
        return call()
    except (NotImplementedError, NoSuchTableError):
        return default


def reflect_schema(engine: Engine, table: str, schema: str | None = None) -> Schema:
    """Reflect a (optionally schema-qualified) table into the canonical Schema.

    Raises ``TableNotFoundError`` when the table does not exist.
    """
    inspector = sa_inspect(engine)
    if not _safe(lambda: inspector.has_table(table, schema=schema), False):
        raise TableNotFoundError(f"Table {_qualified(schema, table)!r} not found.")
    try:
        raw_columns = inspector.get_columns(table, schema=schema)
    except NoSuchTableError:
        raise TableNotFoundError(f"Table {_qualified(schema, table)!r} not found.") from None

    pk_cols = tuple(
        _safe(lambda: inspector.get_pk_constraint(table, schema=schema), {}).get(
            "constrained_columns", []
        )
        or []
    )
    columns = tuple(
        Column(
            name=col["name"],
            logical_type=map_logical_type(col["type"]),
            nullable=bool(col.get("nullable", True)),
            primary_key=col["name"] in pk_cols,
        )
        for col in raw_columns
    )
    foreign_keys = tuple(
        ForeignKey(
            columns=tuple(fk.get("constrained_columns", [])),
            referred_table=fk.get("referred_table", ""),
            referred_columns=tuple(fk.get("referred_columns", [])),
        )
        for fk in _safe(lambda: inspector.get_foreign_keys(table, schema=schema), [])
    )
    unique_constraints = tuple(
        tuple(uc.get("column_names", []))
        for uc in _safe(lambda: inspector.get_unique_constraints(table, schema=schema), [])
    )
    indexes = tuple(
        Index(
            name=ix.get("name"),
            columns=tuple(ix.get("column_names", []) or []),
            unique=bool(ix.get("unique", False)),
        )
        for ix in _safe(lambda: inspector.get_indexes(table, schema=schema), [])
    )
    return Schema(
        columns=columns,
        primary_key=pk_cols,
        foreign_keys=foreign_keys,
        unique_constraints=unique_constraints,
        indexes=indexes,
    )
