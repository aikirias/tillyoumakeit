"""AC-1..AC-6 (1.7): cross-column correlation detection on hand-built Datasets."""

from __future__ import annotations

import json

import pandas as pd

from tymi.domain.artifacts import Column, Dataset, LogicalType, Schema, profile_to_json
from tymi.profiling.profiler import profile_dataset


def _profile(frame: pd.DataFrame, columns: tuple[Column, ...], **kwargs):
    return profile_dataset(Dataset(frame=frame, schema=Schema(columns=columns)), **kwargs)


def test_numeric_positive_correlation() -> None:
    frame = pd.DataFrame({"x": [1, 2, 3, 4, 5], "y": [2, 4, 6, 8, 10]})
    profile = _profile(
        frame, (Column("x", LogicalType.INTEGER), Column("y", LogicalType.INTEGER))
    )
    num = profile.correlations.numeric
    assert num.method == "spearman"
    assert num.columns == ("x", "y")
    # monotone increasing => Spearman == 1.0; diagonal == 1.0
    assert num.matrix[0][0] == 1.0
    assert num.matrix[0][1] == 1.0
    assert num.matrix[1][0] == 1.0


def test_numeric_negative_correlation() -> None:
    frame = pd.DataFrame({"x": [1, 2, 3, 4, 5], "y": [5, 4, 3, 2, 1]})
    profile = _profile(
        frame, (Column("x", LogicalType.INTEGER), Column("y", LogicalType.INTEGER))
    )
    assert profile.correlations.numeric.matrix[0][1] == -1.0


def test_constant_numeric_column_excluded() -> None:
    frame = pd.DataFrame({"x": [1, 2, 3, 4], "k": [7, 7, 7, 7]})
    profile = _profile(
        frame, (Column("x", LogicalType.INTEGER), Column("k", LogicalType.INTEGER))
    )
    # only one non-constant numeric column remains => no matrix
    assert profile.correlations is None or profile.correlations.numeric is None


def test_categorical_perfect_dependence() -> None:
    # b is a deterministic function of a => Cramer's V == 1.0
    frame = pd.DataFrame(
        {"a": ["x", "x", "y", "y", "z", "z"], "b": ["p", "p", "q", "q", "r", "r"]}
    )
    profile = _profile(
        frame, (Column("a", LogicalType.CATEGORICAL), Column("b", LogicalType.CATEGORICAL))
    )
    cat = profile.correlations.categorical
    assert cat.method == "cramers_v"
    assert cat.matrix[0][1] == 1.0
    assert cat.matrix[1][0] == 1.0
    assert cat.matrix[0][0] == 1.0


def test_categorical_independence_is_low() -> None:
    # fully crossed design => near-zero association
    a = ["x", "x", "y", "y"] * 10
    b = ["p", "q", "p", "q"] * 10
    frame = pd.DataFrame({"a": a, "b": b})
    profile = _profile(
        frame, (Column("a", LogicalType.CATEGORICAL), Column("b", LogicalType.CATEGORICAL))
    )
    assert profile.correlations.categorical.matrix[0][1] < 0.05


def test_high_cardinality_categorical_excluded() -> None:
    frame = pd.DataFrame(
        {"id": [f"u{i}" for i in range(20)], "g": ["a", "b"] * 10}
    )
    profile = _profile(
        frame,
        (Column("id", LogicalType.CATEGORICAL), Column("g", LogicalType.CATEGORICAL)),
        categorical_threshold=5,
    )
    # 'id' has 20 distinct > threshold 5 => dropped; only 'g' left => no matrix
    assert profile.correlations is None or profile.correlations.categorical is None


def test_fewer_than_two_columns_omits_matrix() -> None:
    frame = pd.DataFrame({"x": [1, 2, 3, 4]})
    profile = _profile(frame, (Column("x", LogicalType.INTEGER),))
    assert profile.correlations is None


def test_correlations_serialize_to_valid_json_without_nan() -> None:
    frame = pd.DataFrame(
        {
            "x": [1, 2, 3, 4, 5],
            "y": [2, 4, 6, 8, 10],
            "a": ["p", "p", "q", "q", "r"],
            "b": ["u", "u", "v", "v", "w"],
        }
    )
    profile = _profile(
        frame,
        (
            Column("x", LogicalType.INTEGER),
            Column("y", LogicalType.INTEGER),
            Column("a", LogicalType.CATEGORICAL),
            Column("b", LogicalType.CATEGORICAL),
        ),
    )
    payload = profile_to_json(profile)
    assert "NaN" not in payload  # bare NaN is invalid JSON
    data = json.loads(payload)
    assert data["correlations"]["numeric"]["method"] == "spearman"
    assert data["correlations"]["categorical"]["method"] == "cramers_v"


def test_detection_is_deterministic() -> None:
    frame = pd.DataFrame({"x": [3, 1, 4, 1, 5, 9], "y": [2, 7, 1, 8, 2, 8]})
    cols = (Column("x", LogicalType.INTEGER), Column("y", LogicalType.INTEGER))
    first = profile_to_json(_profile(frame, cols))
    second = profile_to_json(_profile(frame, cols))
    assert first == second


def test_two_row_overlap_does_not_fabricate_perfect_correlation() -> None:
    # z overlaps x/y in exactly 2 rows; a 2-point overlap is trivially +/-1.0,
    # so the coefficient must be suppressed to None, not reported as certainty.
    frame = pd.DataFrame(
        {
            "x": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            "y": [2.0, 4.0, 6.0, 8.0, 10.0, 12.0],
            "z": [None, None, None, None, 100.0, 1.0],
        }
    )
    profile = _profile(
        frame,
        (
            Column("x", LogicalType.FLOAT),
            Column("y", LogicalType.FLOAT),
            Column("z", LogicalType.FLOAT),
        ),
    )
    num = profile.correlations.numeric
    zi = num.columns.index("z")
    xi = num.columns.index("x")
    assert num.matrix[zi][xi] is None  # only 2 overlapping rows => undefined
    assert num.matrix[zi][zi] == 1.0  # diagonal stays 1.0


def test_numeric_pair_with_insufficient_overlap_is_none() -> None:
    # x and y never co-occur (disjoint non-null support) => off-diagonal is None,
    # never a bare NaN in the serialized artifact.
    frame = pd.DataFrame({"x": [1.0, 2.0, 3.0, None, None], "y": [None, None, None, 4.0, 5.0]})
    profile = _profile(
        frame, (Column("x", LogicalType.FLOAT), Column("y", LogicalType.FLOAT))
    )
    num = profile.correlations.numeric
    assert num.matrix[0][1] is None
    assert "NaN" not in profile_to_json(profile)


def test_numeric_column_constant_after_coercion_excluded() -> None:
    # distinct raw strings that coerce to the same number => constant after coercion.
    frame = pd.DataFrame({"x": [1, 2, 3, 4], "k": ["1.0", "1.00", "1.000", "1.0000"]})
    profile = _profile(
        frame, (Column("x", LogicalType.FLOAT), Column("k", LogicalType.FLOAT))
    )
    # 'k' collapses to a single numeric value => only one usable column => no matrix
    assert profile.correlations is None or profile.correlations.numeric is None


def test_correlation_representation_holds_only_coefficients() -> None:
    # AD-6: the correlation matrix stores only column names + coefficients in
    # [-1, 1] — never raw row magnitudes (which live, aggregated, in NumericStats).
    frame = pd.DataFrame({"x": [12345, 67890, 13579], "y": [24680, 11111, 22222]})
    profile = _profile(
        frame, (Column("x", LogicalType.INTEGER), Column("y", LogicalType.INTEGER))
    )
    num = profile.correlations.numeric
    assert set(num.columns) == {"x", "y"}
    for row in num.matrix:
        for coeff in row:
            assert coeff is None or -1.0 <= coeff <= 1.0
