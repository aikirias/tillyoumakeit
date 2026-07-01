"""AC-1..AC-4/AC-6 (1.6): per-column profiling on a hand-built Dataset (no DB)."""

from __future__ import annotations

import json

import pandas as pd

from tymi.domain.artifacts import Column, Dataset, LogicalType, Schema, profile_to_json
from tymi.profiling.profiler import profile_dataset


def _dataset() -> Dataset:
    frame = pd.DataFrame(
        {
            "age": [10, 20, 30, 40, None],
            "gender": ["M", "F", "F", "M", "F"],
            "created": pd.to_datetime(
                ["2021-01-01", "2021-02-01", "2021-03-01", "2021-01-15", "2021-02-20"]
            ),
            "note": [f"free text value {i} zzz" for i in range(5)],
            "empty": [None] * 5,
        }
    )
    schema = Schema(
        columns=(
            Column("age", LogicalType.INTEGER),
            Column("gender", LogicalType.STRING),
            Column("created", LogicalType.DATETIME),
            Column("note", LogicalType.STRING),
            Column("empty", LogicalType.STRING),
        )
    )
    return Dataset(frame=frame, schema=schema)


def _by_name(profile) -> dict:
    return {c.name: c for c in profile.columns}


def test_numeric_profile() -> None:
    # categorical_threshold=3 so 'note' (5 distinct) becomes free text, 'gender' stays categorical
    cols = _by_name(profile_dataset(_dataset(), categorical_threshold=3))
    age = cols["age"]
    assert age.count == 4 and age.null_count == 1
    assert age.numeric is not None
    assert age.numeric.min == 10.0 and age.numeric.max == 40.0
    assert age.numeric.mean == 25.0
    assert set(age.numeric.quantiles) == {"5", "25", "50", "75", "95"}
    assert sum(age.numeric.histogram_counts) == 4


def test_categorical_profile() -> None:
    cols = _by_name(profile_dataset(_dataset(), categorical_threshold=3))
    gender = cols["gender"]
    assert gender.categories is not None
    assert {c.value: c.count for c in gender.categories} == {"F": 3, "M": 2}


def test_datetime_profile() -> None:
    cols = _by_name(profile_dataset(_dataset(), categorical_threshold=3))
    created = cols["created"]
    assert created.datetime is not None
    assert created.datetime.min == "2021-01-01T00:00:00"
    assert created.datetime.max == "2021-03-01T00:00:00"
    assert created.datetime.month_frequency  # non-empty


def test_free_text_stores_no_values() -> None:
    profile = profile_dataset(_dataset(), categorical_threshold=3)
    cols = _by_name(profile)
    note = cols["note"]
    assert note.text is not None and note.categories is None
    # AD-6: the raw free-text values must never appear in the serialized profile
    payload = profile_to_json(profile)
    assert "free text value 0 zzz" not in payload
    assert note.text.min_length > 0


def test_all_null_column() -> None:
    cols = _by_name(profile_dataset(_dataset(), categorical_threshold=3))
    empty = cols["empty"]
    assert empty.count == 0 and empty.null_count == 5
    assert empty.numeric is None and empty.categories is None and empty.text is None


def test_low_distinct_long_text_is_not_stored_as_categorical() -> None:
    # mostly-NULL free-text with few distinct but LONG values must NOT leak (AD-6)
    secret_a = "a very long free-text secret note that must never be stored verbatim"
    secret_b = "another long confidential remark that is also far too long to keep"
    frame = pd.DataFrame({"secret": [None] * 8 + [secret_a, secret_b]})
    schema = Schema(columns=(Column("secret", LogicalType.STRING),))
    profile = profile_dataset(Dataset(frame=frame, schema=schema))  # default threshold=50
    col = profile.columns[0]
    assert col.categories is None
    assert col.text is not None
    assert secret_a not in profile_to_json(profile)


def test_categories_ordered_deterministically() -> None:
    frame = pd.DataFrame({"c": ["b", "b", "a", "a", "c"]})
    schema = Schema(columns=(Column("c", LogicalType.CATEGORICAL),))
    cats = profile_dataset(Dataset(frame=frame, schema=schema)).columns[0].categories
    # counts a=2, b=2, c=1 -> highest first, ties by value: a, b, c
    assert [x.value for x in cats] == ["a", "b", "c"]


def test_numeric_column_with_no_numeric_values() -> None:
    frame = pd.DataFrame({"n": ["x", "y", "z"]})  # INTEGER-typed but non-numeric
    schema = Schema(columns=(Column("n", LogicalType.INTEGER),))
    col = profile_dataset(Dataset(frame=frame, schema=schema)).columns[0]
    assert col.numeric is None  # no crash on empty-after-coercion


def test_numeric_inf_is_dropped() -> None:
    frame = pd.DataFrame({"n": [1.0, 2.0, float("inf"), float("-inf")]})
    schema = Schema(columns=(Column("n", LogicalType.FLOAT),))
    col = profile_dataset(Dataset(frame=frame, schema=schema)).columns[0]
    assert col.numeric is not None
    assert col.numeric.max == 2.0  # inf excluded


def test_profile_json_is_valid() -> None:
    payload = profile_to_json(profile_dataset(_dataset()))
    data = json.loads(payload)
    assert data["row_count"] == 5
    assert {c["name"] for c in data["columns"]} == {"age", "gender", "created", "note", "empty"}
