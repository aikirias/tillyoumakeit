"""Story 2.6: multi-destination export (file formats + direct SQL load)."""

from __future__ import annotations

import pandas as pd
import pytest
from sqlalchemy import create_engine, make_url

from tymi.core.errors import ExportError
from tymi.domain.artifacts import Column, Dataset, LogicalType, Schema
from tymi.engines._base import SqlAlchemyEngineAdapter
from tymi.engines._introspect import logical_to_sqltype
from tymi.io.exporters import CsvExporter, JsonExporter, ParquetExporter, get_exporter
from tymi.io.schema_map import normalize_for_export


def _dataset() -> Dataset:
    frame = pd.DataFrame(
        {
            "n": pd.Series([5.0, None, 7.0]),  # float-backed but declared INTEGER
            "x": [1.5, 2.5, 3.5],
            "flag": [True, False, None],
            "born": ["2020-01-01", "2021-06-15", "2019-03-03"],
            "name": ["ada", "grace", None],
        }
    )
    schema = Schema(
        columns=(
            Column("n", LogicalType.INTEGER),
            Column("x", LogicalType.FLOAT),
            Column("flag", LogicalType.BOOLEAN),
            Column("born", LogicalType.DATETIME),
            Column("name", LogicalType.STRING),
        )
    )
    return Dataset(frame=frame, schema=schema)


# --- AR-10 Schema-driven normalization -------------------------------------


def test_normalize_maps_from_schema_not_pandas_dtype() -> None:
    out = normalize_for_export(_dataset())
    assert list(out.columns) == ["n", "x", "flag", "born", "name"]  # Schema order
    assert out["n"].dtype == "Int64" and out["n"].tolist() == [5, pd.NA, 7]
    assert out["x"].dtype == "float64"
    assert out["flag"].dtype == "boolean"
    assert pd.api.types.is_datetime64_any_dtype(out["born"])
    assert out["name"].tolist()[:2] == ["ada", "grace"]


def test_logical_to_sqltype_covers_every_logical_type() -> None:
    from sqlalchemy import types as satypes

    assert isinstance(logical_to_sqltype(LogicalType.INTEGER), satypes.BigInteger)
    assert isinstance(logical_to_sqltype(LogicalType.FLOAT), satypes.Float)
    assert isinstance(logical_to_sqltype(LogicalType.BOOLEAN), satypes.Boolean)
    assert isinstance(logical_to_sqltype(LogicalType.DATETIME), satypes.DateTime)
    assert isinstance(logical_to_sqltype(LogicalType.STRING), satypes.Text)
    assert isinstance(logical_to_sqltype(LogicalType.CATEGORICAL), satypes.Text)


# --- file exporters: determinism + re-import -------------------------------


def test_csv_is_deterministic_and_reimportable(tmp_path) -> None:
    exp = CsvExporter()
    a, b = tmp_path / "a.csv", tmp_path / "b.csv"
    exp.export(_dataset(), target=str(a))
    exp.export(_dataset(), target=str(b))
    assert a.read_bytes() == b.read_bytes()  # byte-identical (NFR-4)
    back = pd.read_csv(a, parse_dates=["born"])
    assert list(back.columns) == ["n", "x", "flag", "born", "name"]
    assert back["n"].tolist() == [5, 7] or back["n"].dropna().tolist() == [5.0, 7.0]
    assert back["born"].iloc[0] == pd.Timestamp("2020-01-01")  # datetime re-imports


def test_json_is_deterministic_and_reimportable(tmp_path) -> None:
    exp = JsonExporter()
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    exp.export(_dataset(), target=str(a))
    exp.export(_dataset(), target=str(b))
    assert a.read_bytes() == b.read_bytes()
    back = pd.read_json(a)
    assert len(back) == 3
    assert list(back.columns) == ["n", "x", "flag", "born", "name"]


def test_parquet_is_deterministic_and_reimportable(tmp_path) -> None:
    pytest.importorskip("pyarrow")
    exp = ParquetExporter()
    a, b = tmp_path / "a.parquet", tmp_path / "b.parquet"
    exp.export(_dataset(), target=str(a))
    exp.export(_dataset(), target=str(b))
    assert a.read_bytes() == b.read_bytes()  # byte-identical for a fixed pyarrow
    back = pd.read_parquet(a)
    assert back["n"].dtype == "Int64"  # dtype round-trips (unlike CSV)
    assert pd.api.types.is_datetime64_any_dtype(back["born"])


def test_json_preserves_float_precision() -> None:
    # regression (pandas default double_precision=10 truncates); 1/3 must survive.
    ds = Dataset(
        frame=pd.DataFrame({"x": [1 / 3]}),
        schema=Schema(columns=(Column("x", LogicalType.FLOAT),)),
    )
    # pandas' default double_precision=10 would give "0.3333333333"; 15 keeps far more.
    assert "0.33333333333333" in JsonExporter().render(ds)


def test_datetime_subsecond_is_preserved_in_csv_and_json(tmp_path) -> None:
    # regression (CSV truncated to whole seconds, JSON to ms); both must round-trip.
    stamp = pd.Timestamp("2020-08-21 03:04:16.624192")
    ds = Dataset(
        frame=pd.DataFrame({"t": [stamp]}),
        schema=Schema(columns=(Column("t", LogicalType.DATETIME),)),
    )
    csv_path = tmp_path / "a.csv"
    CsvExporter().export(ds, target=str(csv_path))
    # CSV round-trips the full sub-second value (old code truncated to whole seconds)
    assert pd.read_csv(csv_path, parse_dates=["t"])["t"].iloc[0] == stamp
    # JSON keeps the sub-second in the serialized string (old code kept only ms)
    assert ".624192" in JsonExporter().render(ds)


def test_string_column_backed_by_extension_dtype_is_stringified() -> None:
    # regression (`.where` kept the Int64 dtype so JSON emitted a number).
    ds = Dataset(
        frame=pd.DataFrame({"code": pd.array([5, 3], dtype="Int64")}),
        schema=Schema(columns=(Column("code", LogicalType.STRING),)),
    )
    assert normalize_for_export(ds)["code"].tolist() == ["5", "3"]
    assert '"5"' in JsonExporter().render(ds)


def test_get_exporter_unknown_format_raises() -> None:
    with pytest.raises(ExportError, match="Unknown export format"):
        get_exporter("xml")


def test_export_to_unwritable_path_raises_export_error(tmp_path) -> None:
    # a directory-as-file target cannot be written → typed ExportError, no traceback.
    with pytest.raises(ExportError, match="Could not write"):
        CsvExporter().export(_dataset(), target=str(tmp_path))  # tmp_path is a dir


def test_render_stdout_matches_file(tmp_path) -> None:
    exp = CsvExporter()
    path = tmp_path / "a.csv"
    exp.export(_dataset(), target=str(path))
    assert exp.render(_dataset()) == path.read_text(encoding="utf-8")


# --- direct SQL load over the shared SQLAlchemy path (via sqlite) -----------


class _SqliteAdapter(SqlAlchemyEngineAdapter):
    """A sqlite-backed adapter to exercise ``load`` end-to-end without a container."""

    DIALECT = "sqlite"

    def __init__(self, path: str) -> None:  # noqa: D401 - no ConnectionConfig needed
        self._path = path

    def build_url(self):  # type: ignore[override]
        return make_url(f"sqlite:///{self._path}")


def test_load_creates_table_from_schema_and_inserts_rows(tmp_path) -> None:
    from sqlalchemy import inspect as sa_inspect
    from sqlalchemy import types as satypes

    db = tmp_path / "dest.db"
    adapter = _SqliteAdapter(str(db))
    adapter.load(_dataset(), table="people")
    adapter.load(_dataset(), table="people")  # idempotent: replace, not append

    engine = create_engine(f"sqlite:///{db}")
    try:
        back = pd.read_sql_table("people", engine)
        cols = {c["name"]: c["type"] for c in sa_inspect(engine).get_columns("people")}
    finally:
        engine.dispose()
    assert len(back) == 3  # replaced, not doubled
    assert set(back.columns) == {"n", "x", "flag", "born", "name"}
    assert back["n"].dropna().astype(int).tolist() == [5, 7]
    assert back["name"].tolist()[:2] == ["ada", "grace"]
    # DDL types came from the Schema map (AR-10), not pandas inference: a STRING lands
    # as TEXT and a DATETIME as a date/time type (never both inferred as TEXT).
    assert isinstance(cols["name"], satypes.Text)
    assert isinstance(cols["born"], (satypes.DateTime, satypes.Date, satypes.TIMESTAMP))
    assert isinstance(cols["n"], (satypes.Integer, satypes.BigInteger))


# --- CLI export surface -----------------------------------------------------


def _saved_profile(tmp_path):
    from tymi.profiling.profile_io import save_profile
    from tymi.profiling.profiler import profile_dataset

    profile = profile_dataset(_dataset())
    path = tmp_path / "p.yaml"
    save_profile(profile, path)
    return path


def test_cli_generate_to_json_file(tmp_path) -> None:
    from typer.testing import CliRunner

    from tymi.cli.app import app

    out = tmp_path / "out.json"
    prof = str(_saved_profile(tmp_path))
    result = CliRunner().invoke(
        app, ["generate", "-p", prof, "-n", "5", "--to", "json", "-o", str(out)]
    )
    assert result.exit_code == 0, result.stdout
    assert out.exists() and len(pd.read_json(out)) == 5


def test_cli_generate_parquet_without_out_errors(tmp_path) -> None:
    from typer.testing import CliRunner

    from tymi.cli.app import app

    result = CliRunner().invoke(
        app, ["generate", "-p", str(_saved_profile(tmp_path)), "-n", "5", "--to", "parquet"]
    )
    assert result.exit_code == 2
    assert "needs --out" in result.stdout


def test_cli_generate_unknown_format_errors(tmp_path) -> None:
    from typer.testing import CliRunner

    from tymi.cli.app import app

    result = CliRunner().invoke(
        app, ["generate", "-p", str(_saved_profile(tmp_path)), "-n", "5", "--to", "xml"]
    )
    assert result.exit_code == 2
    assert "Unknown export format" in result.stdout


def test_cli_generate_sql_without_target_errors(tmp_path) -> None:
    from typer.testing import CliRunner

    from tymi.cli.app import app

    result = CliRunner().invoke(
        app, ["generate", "-p", str(_saved_profile(tmp_path)), "-n", "5", "--to", "sql"]
    )
    assert result.exit_code == 2
    assert "requires --engine, --config and --table" in result.stdout
