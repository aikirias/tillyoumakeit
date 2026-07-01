"""TYMI command-line interface (driving adapter).

Most subcommands are still stubs (they explain they are not implemented and exit
with code 2). ``test-connection`` is real. ``tymi --help`` lists them all and
exits 0.
"""

from __future__ import annotations

from pathlib import Path

import typer

from tymi.config import load_config
from tymi.core.errors import ConfigError, EngineConnectionError
from tymi.core.plugins import load_engines

app = typer.Typer(
    name="tymi",
    help="Fake It Till You Make It — faithful synthetic data + data chaos monkey.",
    no_args_is_help=True,
    add_completion=False,
)

_NOT_IMPLEMENTED_EXIT = 2

_STUB_COMMANDS = {
    "schema": "Introspect and print a table's schema.",
    "sample": "Sample rows from a source table.",
    "profile": "Build a statistical Profile of a table.",
    "generate": "Generate faithful synthetic data from a Profile.",
    "chaos": "Generate chaotic data from a Profile.",
    "report": "Produce fidelity / quality & privacy reports.",
    "export": "Export generated data to files or an engine.",
    "ui": "Launch the Streamlit web UI.",
}


def _make_stub(command: str, summary: str):
    def _stub() -> None:
        typer.echo(f"'{command}' is not implemented yet ({summary})")
        raise typer.Exit(code=_NOT_IMPLEMENTED_EXIT)

    _stub.__doc__ = summary
    return _stub


for _name, _summary in _STUB_COMMANDS.items():
    app.command(name=_name)(_make_stub(_name, _summary))


@app.command(name="test-connection")
def test_connection(
    engine: str = typer.Option(..., "--engine", "-e", help="Engine name, e.g. 'mssql'."),
    config: Path = typer.Option(
        ..., "--config", "-c", exists=True, dir_okay=False, help="Path to the YAML config."
    ),
) -> None:
    """Test a connection to a source/destination engine."""
    try:
        cfg = load_config(config)
    except ConfigError as exc:
        typer.echo(f"Invalid config: {exc}")
        raise typer.Exit(code=2) from None

    engines = load_engines()
    adapter_cls = engines.get(engine)
    if adapter_cls is None:
        typer.echo(f"Unknown engine {engine!r}. Available: {sorted(engines)}")
        raise typer.Exit(code=2)

    connection = cfg.source.connection
    if connection is None:
        typer.echo("No 'source.connection' section found in the config file.")
        raise typer.Exit(code=2)

    adapter = adapter_cls(connection)
    try:
        adapter.test_connection()
    except EngineConnectionError as exc:
        typer.echo(f"Connection failed: {exc}")
        raise typer.Exit(code=1) from None
    typer.echo(f"Connection to {engine!r} OK.")


if __name__ == "__main__":  # pragma: no cover
    app()
