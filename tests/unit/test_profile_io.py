"""AC-1..AC-6 (1.8): Profile save/load round-trip, version gating, offline CLI."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
import yaml
from typer.testing import CliRunner

from tymi.cli.app import app
from tymi.core.errors import ProfileError, ProfileVersionError
from tymi.domain.artifacts import (
    Column,
    Dataset,
    ForeignKey,
    Index,
    LogicalType,
    Schema,
)
from tymi.profiling.profile_io import load_profile, save_profile
from tymi.profiling.profiler import profile_dataset

runner = CliRunner()


def _dataset() -> Dataset:
    frame = pd.DataFrame(
        {
            "age": [10, 20, 30, 40, None],
            "gender": ["M", "F", "F", "M", "F"],
            "created": pd.to_datetime(
                ["2021-01-01", "2021-02-01", "2021-03-01", "2021-01-15", "2021-02-20"]
            ),
            "note": [f"free text value {i} zzz" for i in range(5)],
            "score": [1.5, 3.0, 4.5, 6.0, 7.5],
        }
    )
    schema = Schema(
        columns=(
            Column("age", LogicalType.INTEGER),
            Column("gender", LogicalType.CATEGORICAL),
            Column("created", LogicalType.DATETIME),
            Column("note", LogicalType.STRING),
            Column("score", LogicalType.FLOAT),
        ),
        primary_key=("age",),
    )
    return Dataset(frame=frame, schema=schema)


def test_round_trip_equals(tmp_path: Path) -> None:
    profile = profile_dataset(_dataset(), categorical_threshold=3)
    path = tmp_path / "p.profile.yaml"
    save_profile(profile, path)
    loaded = load_profile(path)
    assert loaded == profile


def test_round_trip_preserves_schema_version(tmp_path: Path) -> None:
    profile = profile_dataset(_dataset())
    path = tmp_path / "p.yaml"
    save_profile(profile, path)
    assert load_profile(path).schema_version == profile.schema_version == "1.0.0"


def test_saved_file_is_human_readable_yaml(tmp_path: Path) -> None:
    profile = profile_dataset(_dataset(), categorical_threshold=3)
    path = tmp_path / "p.yaml"
    save_profile(profile, path)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["schema_version"] == "1.0.0"
    assert data["row_count"] == 5
    assert {c["name"] for c in data["columns"]} == {"age", "gender", "created", "note", "score"}


def test_no_raw_free_text_in_saved_file(tmp_path: Path) -> None:
    # AD-6: persistence must not introduce raw values the Profile never held.
    profile = profile_dataset(_dataset(), categorical_threshold=3)
    path = tmp_path / "p.yaml"
    save_profile(profile, path)
    assert "free text value 0 zzz" not in path.read_text(encoding="utf-8")


def test_unsupported_major_raises_version_error(tmp_path: Path) -> None:
    path = tmp_path / "p.yaml"
    path.write_text("schema_version: '2.0.0'\nrow_count: 0\ncolumns: []\n", encoding="utf-8")
    with pytest.raises(ProfileVersionError):
        load_profile(path)


def test_malformed_version_raises_version_error(tmp_path: Path) -> None:
    path = tmp_path / "p.yaml"
    path.write_text("schema_version: 'not-a-version'\ncolumns: []\n", encoding="utf-8")
    with pytest.raises(ProfileVersionError):
        load_profile(path)


def test_non_mapping_root_raises_profile_error(tmp_path: Path) -> None:
    path = tmp_path / "p.yaml"
    path.write_text("- just\n- a\n- list\n", encoding="utf-8")
    with pytest.raises(ProfileError):
        load_profile(path)


def test_missing_file_raises_profile_error(tmp_path: Path) -> None:
    with pytest.raises(ProfileError):
        load_profile(tmp_path / "does-not-exist.yaml")


@pytest.mark.parametrize(
    "body",
    [
        "schema_version: '1.0.0'\nschema: [not, a, mapping]\ncolumns: []\n",  # schema is a list
        "schema_version: '1.0.0'\ncolumns: hello\n",  # columns is a scalar string
        "schema_version: '1.0.0'\ncolumns: []\ncorrelations: 7\n",  # correlations is a scalar
    ],
)
def test_wrong_shaped_sections_raise_profile_error(tmp_path: Path, body: str) -> None:
    # hand-edited files with the wrong shape must surface as ProfileError, not a
    # raw AttributeError escaping load_profile.
    path = tmp_path / "p.yaml"
    path.write_text(body, encoding="utf-8")
    with pytest.raises(ProfileError):
        load_profile(path)


def test_correlations_round_trip(tmp_path: Path) -> None:
    frame = pd.DataFrame({"x": [1, 2, 3, 4, 5], "y": [2, 4, 6, 8, 10]})
    schema = Schema(columns=(Column("x", LogicalType.INTEGER), Column("y", LogicalType.INTEGER)))
    profile = profile_dataset(Dataset(frame=frame, schema=schema))
    path = tmp_path / "p.yaml"
    save_profile(profile, path)
    loaded = load_profile(path)
    assert loaded == profile
    assert loaded.correlations.numeric.matrix[0][1] == 1.0


def test_rich_schema_round_trips(tmp_path: Path) -> None:
    # exercise Schema fields the value-based dataset doesn't: FK, unique (tuple of
    # tuples), indexes — reconstruction must rebuild tuples, not lists, for ==.
    frame = pd.DataFrame({"id": [1, 2, 3], "email": ["a", "b", "c"]})
    schema = Schema(
        columns=(
            Column("id", LogicalType.INTEGER, nullable=False, primary_key=True),
            Column("email", LogicalType.STRING),
        ),
        primary_key=("id",),
        foreign_keys=(ForeignKey(("id",), "other", ("other_id",)),),
        unique_constraints=(("email",), ("id", "email")),
        indexes=(Index("ix_email", ("email",), unique=True),),
    )
    profile = profile_dataset(Dataset(frame=frame, schema=schema))
    path = tmp_path / "p.yaml"
    save_profile(profile, path)
    loaded = load_profile(path)
    assert loaded == profile
    assert loaded.schema.unique_constraints == (("email",), ("id", "email"))
    assert loaded.schema.foreign_keys[0].columns == ("id",)


def test_cli_save_then_load_offline(tmp_path: Path) -> None:
    # Save a profile to disk directly, then exercise the offline CLI --load path.
    profile = profile_dataset(_dataset())
    path = tmp_path / "p.profile.yaml"
    save_profile(profile, path)
    result = runner.invoke(app, ["profile", "--load", str(path)])
    assert result.exit_code == 0
    assert '"row_count": 5' in result.output


def test_cli_profile_without_table_or_load_errors() -> None:
    result = runner.invoke(app, ["profile"])
    assert result.exit_code == 2
    assert "requires TABLE" in result.output


def test_cli_load_with_out_is_rejected(tmp_path: Path) -> None:
    profile = profile_dataset(_dataset())
    path = tmp_path / "p.yaml"
    save_profile(profile, path)
    result = runner.invoke(app, ["profile", "--load", str(path), "-o", str(tmp_path / "o.yaml")])
    assert result.exit_code == 2
    assert "cannot be combined" in result.output
