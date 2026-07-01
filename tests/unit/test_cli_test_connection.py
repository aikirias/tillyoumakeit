"""AC-3/AC-5: `test-connection` CLI guard rails (no DB required)."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from tymi.cli.app import app

runner = CliRunner()


def _config(tmp_path: Path, body: str) -> str:
    path = tmp_path / "config.yaml"
    path.write_text(body, encoding="utf-8")
    return str(path)


def test_unknown_engine_exits_2(tmp_path: Path) -> None:
    cfg = _config(tmp_path, "schema_version: '1.0.0'\nsource:\n  connection:\n    host: h\n")
    result = runner.invoke(app, ["test-connection", "--engine", "nope", "--config", cfg])
    assert result.exit_code == 2
    assert "Unknown engine" in result.output


def test_missing_connection_exits_2(tmp_path: Path) -> None:
    cfg = _config(tmp_path, "schema_version: '1.0.0'\n")
    result = runner.invoke(app, ["test-connection", "--engine", "mssql", "--config", cfg])
    assert result.exit_code == 2
    assert "connection" in result.output.lower()


def test_engine_config_mismatch_exits_2(tmp_path: Path) -> None:
    cfg = _config(
        tmp_path,
        "schema_version: '1.0.0'\nsource:\n  engine: postgres\n  connection:\n    host: h\n",
    )
    result = runner.invoke(app, ["test-connection", "--engine", "mssql", "--config", cfg])
    assert result.exit_code == 2
    assert "does not match" in result.output
