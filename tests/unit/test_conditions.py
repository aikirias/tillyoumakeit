"""AC-1/AC-5 (2.4): condition parsing, validation and typed errors."""

from __future__ import annotations

import pandas as pd
import pytest

from tymi.core.errors import GenerationError
from tymi.domain.artifacts import Column, LogicalType, Profile, Schema
from tymi.synth.conditions import (
    Between,
    Equals,
    Members,
    parse_condition,
    parse_conditions,
    satisfies,
    validate_conditions,
)


def test_parse_equality_plain_and_quoted() -> None:
    assert parse_condition("region=LATAM") == Equals("region", "LATAM")
    assert parse_condition("region = 'LATAM'") == Equals("region", "LATAM")
    assert parse_condition('name="Ada Lovelace"') == Equals("name", "Ada Lovelace")


def test_parse_range_is_inclusive_two_bounds() -> None:
    assert parse_condition("age in [18,25]") == Between("age", "18", "25")
    assert parse_condition("age IN [ 18 , 25 ]") == Between("age", "18", "25")


def test_parse_membership_set() -> None:
    assert parse_condition("region in {LATAM,EMEA,APAC}") == Members(
        "region", ("LATAM", "EMEA", "APAC")
    )
    assert parse_condition("region in {'LATAM', 'EMEA'}") == Members("region", ("LATAM", "EMEA"))


def test_range_requires_exactly_two_bounds() -> None:
    with pytest.raises(GenerationError, match="exactly two bounds"):
        parse_condition("age in [18,25,30]")
    with pytest.raises(GenerationError, match="exactly two bounds"):
        parse_condition("age in [18]")


def test_mismatched_brackets_error() -> None:
    with pytest.raises(GenerationError, match="mismatched brackets"):
        parse_condition("age in [18,25}")


def test_unparsable_condition_errors() -> None:
    with pytest.raises(GenerationError, match="could not parse"):
        parse_condition("age >= 18")
    with pytest.raises(GenerationError, match="could not parse"):
        parse_condition("region=")


def test_empty_membership_errors() -> None:
    with pytest.raises(GenerationError, match="empty value list"):
        parse_condition("region in {}")


def test_parse_conditions_rejects_duplicate_column() -> None:
    with pytest.raises(GenerationError, match="more than one condition"):
        parse_conditions(["age in [18,25]", "age=30"])


def _profile() -> Profile:
    schema = Schema(
        columns=(
            Column("region", LogicalType.CATEGORICAL),
            Column("age", LogicalType.INTEGER),
            Column("created", LogicalType.DATETIME),
        )
    )
    return Profile(schema=schema)


def test_validate_unknown_column_errors() -> None:
    with pytest.raises(GenerationError, match="unknown column 'nope'"):
        validate_conditions({"nope": Equals("nope", "x")}, _profile())


def test_validate_range_on_categorical_errors() -> None:
    with pytest.raises(GenerationError, match="range condition on non-numeric"):
        validate_conditions({"region": Between("region", "a", "b")}, _profile())


def test_validate_allows_range_on_numeric_and_datetime() -> None:
    validate_conditions({"age": Between("age", "18", "25")}, _profile())
    validate_conditions({"created": Between("created", "2020-01-01", "2020-12-31")}, _profile())


def test_satisfies_helper() -> None:
    frame = pd.DataFrame({"region": ["LATAM", "LATAM"], "age": [20, 24]})
    assert satisfies(frame, {"region": Equals("region", "LATAM")})
    assert satisfies(frame, {"age": Between("age", "18", "25")})
    assert not satisfies(frame, {"age": Between("age", "21", "25")})
    assert not satisfies(frame, {"region": Members("region", ("EMEA",))})


def test_satisfies_numeric_and_reversed_bounds() -> None:
    # regression: float columns compare numerically ("5" matches 5.0) and reversed
    # range bounds are order-normalized like the sampler.
    frame = pd.DataFrame({"price": [5.0, 5.0], "age": [20, 24]})
    assert satisfies(frame, {"price": Equals("price", "5")})
    assert satisfies(frame, {"price": Members("price", ("5", "6"))})
    assert satisfies(frame, {"age": Between("age", "25", "18")})  # reversed → [18,25]
