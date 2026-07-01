"""TYMI command-line interface (driving adapter).

Some subcommands are still stubs (they exit with code 2). ``test-connection``
and ``schema`` are real. ``tymi --help`` lists them all and exits 0.
"""

from __future__ import annotations

from pathlib import Path

import typer

from tymi.config import load_config
from tymi.core.errors import ConfigError, EngineConnectionError, TableNotFoundError
from tymi.core.plugins import load_engines
from tymi.core.rng import make_rng
from tymi.domain.artifacts import schema_to_json

app = typer.Typer(
    name="tymi",
    help="Fake It Till You Make It — faithful synthetic data + data chaos monkey.",
    no_args_is_help=True,
    add_completion=False,
)

_NOT_IMPLEMENTED_EXIT = 2

_STUB_COMMANDS = {
    "profile": "Build a statistical Profile of a table.",
    "generate": "Generate faithful synthetic data from a Profile.",
    "chaos": "Generate chaotic data from a Profile.",
    "report": "Produce fidelity / quality & privacy reports.",
    "export": "Export generated data to files or an engine.",
    "ui": "Launch the Streamlit web UI.",
}

_ENGINE_OPTION = typer.Option(..., "--engine", "-e", help="Engine name, e.g. 'postgres'.")
_CONFIG_OPTION = typer.Option(
    ..., "--config", "-c", exists=True, dir_okay=False, help="Path to the YAML config."
)


def _make_stub(command: str, summary: str):
    def _stub() -> None:
        typer.echo(f"'{command}' is not implemented yet ({summary})")
        raise typer.Exit(code=_NOT_IMPLEMENTED_EXIT)

    _stub.__doc__ = summary
    return _stub


for _name, _summary in _STUB_COMMANDS.items():
    app.command(name=_name)(_make_stub(_name, _summary))


def _load_adapter(engine: str, config: Path):
    """Load config and build the requested engine adapter, or exit non-zero."""
    try:
        cfg = load_config(config)
    except ConfigError as exc:
        typer.echo(f"Invalid config: {exc}")
        raise typer.Exit(code=2) from None

    if cfg.source.engine is not None and cfg.source.engine != engine:
        typer.echo(
            f"--engine {engine!r} does not match source.engine "
            f"{cfg.source.engine!r} in the config file."
        )
        raise typer.Exit(code=2)

    engines = load_engines()
    adapter_cls = engines.get(engine)
    if adapter_cls is None:
        typer.echo(f"Unknown engine {engine!r}. Available: {sorted(engines)}")
        raise typer.Exit(code=2)

    connection = cfg.source.connection
    if connection is None:
        typer.echo("No 'source.connection' section found in the config file.")
        raise typer.Exit(code=2)

    return adapter_cls(connection)


@app.command(name="test-connection")
def test_connection(engine: str = _ENGINE_OPTION, config: Path = _CONFIG_OPTION) -> None:
    """Test a connection to a source/destination engine."""
    adapter = _load_adapter(engine, config)
    try:
        adapter.test_connection()
    except EngineConnectionError as exc:
        typer.echo(f"Connection failed: {exc}")
        raise typer.Exit(code=1) from None
    typer.echo(f"Connection to {engine!r} OK.")


@app.command(name="schema")
def schema(
    table: str = typer.Argument(..., help="Table name to introspect."),
    engine: str = _ENGINE_OPTION,
    config: Path = _CONFIG_OPTION,
) -> None:
    """Introspect and print a table's schema as JSON."""
    adapter = _load_adapter(engine, config)
    try:
        result = adapter.introspect(table)
    except TableNotFoundError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from None
    except EngineConnectionError as exc:
        typer.echo(f"Connection failed: {exc}")
        raise typer.Exit(code=1) from None
    typer.echo(schema_to_json(result))


@app.command(name="sample")
def sample(
    table: str = typer.Argument(..., help="Table name to sample."),
    engine: str = _ENGINE_OPTION,
    config: Path = _CONFIG_OPTION,
    rows: int = typer.Option(1000, "--rows", "-n", min=1, help="Number of rows to sample."),
    seed: int = typer.Option(0, "--seed", "-s", help="Seed for reproducible sampling."),
) -> None:
    """Sample rows from a source table and print them as CSV."""
    adapter = _load_adapter(engine, config)
    if not adapter.reproducible_sample:
        typer.echo(f"Note: sampling for {engine!r} is not seed-reproducible.", err=True)
    try:
        dataset = adapter.sample(table, rows=rows, rng=make_rng(seed))
    except TableNotFoundError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from None
    except EngineConnectionError as exc:
        typer.echo(f"Connection failed: {exc}")
        raise typer.Exit(code=1) from None
    typer.echo(dataset.frame.to_csv(index=False))


if __name__ == "__main__":  # pragma: no cover
    app()
