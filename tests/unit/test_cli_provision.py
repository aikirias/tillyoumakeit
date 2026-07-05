"""PRD 1 Story 3.3: the `tymi provision` CLI command (AD-19)."""

from __future__ import annotations

import pandas as pd
from typer.testing import CliRunner

from tymi.cli import app as cli_app
from tymi.config.spec import DestinationSpec, bootstrap_spec, save_spec
from tymi.domain.artifacts import Column, Dataset, LogicalType, Schema
from tymi.profiling.profiler import profile_dataset

runner = CliRunner()

_SCHEMA = Schema(
    columns=(
        Column("id", LogicalType.INTEGER, primary_key=True),
        Column("email", LogicalType.STRING),
    ),
    primary_key=("id",),
)


class _FakeAdapter:
    supports_write = True

    def __init__(self) -> None:
        self.loaded: list[str] = []
        self.streamed: list[str] = []

    def load(self, dataset, *, table: str) -> None:
        self.loaded.append(table)

    def load_stream(self, chunks, *, table: str) -> int:
        rows = sum(len(ds.frame) for ds in chunks)  # consume the chunk generator
        self.streamed.append(table)
        return rows


def _write_spec(tmp_path, *, environment="nonprod", host="dev-db"):
    profile = profile_dataset(
        Dataset(
            frame=pd.DataFrame({"id": range(10), "email": [f"u{i}@x.com" for i in range(10)]}),
            schema=_SCHEMA,
        ),
        sensitive_columns=["email"],
        salt="s",
    )
    spec = bootstrap_spec({"customers": profile}, seed=1)
    spec.destination = DestinationSpec(environment=environment, host=host, database="app")
    path = tmp_path / "spec.yaml"
    save_spec(spec, path)
    return path


def _write_config(tmp_path, *, host="dev-db", name="cfg.yaml"):
    path = tmp_path / name
    path.write_text(
        f"schema_version: '1.0.0'\nsource:\n  engine: postgres\n  connection:\n    host: {host}\n",
        encoding="utf-8",
    )
    return path


def _invoke(spec_path, cfg):
    return runner.invoke(
        cli_app.app,
        ["provision", "--spec", str(spec_path), "--engine", "postgres", "--config", str(cfg)],
    )


def test_provision_command_reports_success(tmp_path, monkeypatch) -> None:
    adapter = _FakeAdapter()
    monkeypatch.setattr(cli_app, "_load_adapter", lambda engine, config: adapter)
    result = _invoke(_write_spec(tmp_path, host="dev-db"), _write_config(tmp_path, host="dev-db"))
    assert result.exit_code == 0, result.output
    assert "Provisioned 1 table(s)" in result.output
    assert "Consistency-unit fingerprint:" in result.output
    assert adapter.loaded == ["customers"]


def test_provision_command_fails_closed_on_prod_spec(tmp_path, monkeypatch) -> None:
    adapter = _FakeAdapter()
    monkeypatch.setattr(cli_app, "_load_adapter", lambda engine, config: adapter)
    result = _invoke(
        _write_spec(tmp_path, host="prod-db-01"), _write_config(tmp_path, host="prod-db-01")
    )
    assert result.exit_code == 2
    assert "guardrail failed closed" in result.output
    assert adapter.loaded == []  # nothing written


def test_provision_command_fails_closed_on_prod_connection_even_if_spec_affirms_nonprod(
    tmp_path, monkeypatch
) -> None:
    # The Spec affirms a nonprod host, but the real --config connection points at prod: fail closed.
    adapter = _FakeAdapter()
    monkeypatch.setattr(cli_app, "_load_adapter", lambda engine, config: adapter)
    result = _invoke(
        _write_spec(tmp_path, host="dev-db"), _write_config(tmp_path, host="prod-db-01")
    )
    assert result.exit_code == 2
    assert "guardrail failed closed" in result.output
    assert adapter.loaded == []


def test_provision_command_fails_closed_on_host_mismatch(tmp_path, monkeypatch) -> None:
    # Spec affirms dev-db, config connects to a different (non-prod) host → fail closed on mismatch.
    adapter = _FakeAdapter()
    monkeypatch.setattr(cli_app, "_load_adapter", lambda engine, config: adapter)
    result = _invoke(
        _write_spec(tmp_path, host="dev-db"), _write_config(tmp_path, host="staging-db")
    )
    assert result.exit_code == 2
    assert "does not match" in result.output
    assert adapter.loaded == []


def test_provision_command_stream_flag_reaches_the_pipeline(tmp_path, monkeypatch) -> None:
    adapter = _FakeAdapter()
    monkeypatch.setattr(cli_app, "_load_adapter", lambda engine, config: adapter)
    result = runner.invoke(
        cli_app.app,
        [
            "provision", "--spec", str(_write_spec(tmp_path, host="dev-db")),
            "--engine", "postgres", "--config", str(_write_config(tmp_path, host="dev-db")),
            "--stream",
        ],
    )
    assert result.exit_code == 0, result.output
    assert adapter.streamed == ["customers"]  # went through the streaming path
    assert adapter.loaded == []  # not the in-memory path


def test_provision_command_is_registered() -> None:
    result = runner.invoke(cli_app.app, ["--help"])
    assert "provision" in result.output
