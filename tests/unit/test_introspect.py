"""AC-2/AC-4 (1.4): type mapping and Schema JSON serialization (no DB)."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import types as satypes

from tymi.domain.artifacts import Column, ForeignKey, LogicalType, Schema, schema_to_json
from tymi.engines._introspect import map_logical_type

TYPE_CASES = [
    (satypes.Integer(), LogicalType.INTEGER),
    (satypes.BigInteger(), LogicalType.INTEGER),
    (satypes.Boolean(), LogicalType.BOOLEAN),
    (satypes.Numeric(), LogicalType.FLOAT),
    (satypes.Float(), LogicalType.FLOAT),
    (satypes.DateTime(), LogicalType.DATETIME),
    (satypes.Date(), LogicalType.DATETIME),
    (satypes.String(), LogicalType.STRING),
    (satypes.Text(), LogicalType.STRING),
    (satypes.Enum("a", "b", name="e"), LogicalType.CATEGORICAL),
]


@pytest.mark.parametrize(("sa_type", "expected"), TYPE_CASES)
def test_type_mapping(sa_type: object, expected: LogicalType) -> None:
    assert map_logical_type(sa_type) == expected


def test_schema_to_json_shape() -> None:
    schema = Schema(
        columns=(
            Column("id", LogicalType.INTEGER, nullable=False, primary_key=True),
            Column("parent_id", LogicalType.INTEGER),
        ),
        primary_key=("id",),
        foreign_keys=(ForeignKey(("parent_id",), "parent", ("id",)),),
    )
    data = json.loads(schema_to_json(schema))
    assert [c["name"] for c in data["columns"]] == ["id", "parent_id"]
    assert data["columns"][0]["logical_type"] == "integer"
    assert data["columns"][0]["primary_key"] is True
    assert data["primary_key"] == ["id"]
    assert data["foreign_keys"][0]["referred_table"] == "parent"
    assert data["foreign_keys"][0]["columns"] == ["parent_id"]
