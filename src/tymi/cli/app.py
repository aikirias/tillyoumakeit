"""TYMI command-line interface (driving adapter).

For the scaffold story every subcommand is a stub: it explains that the command
is not implemented yet and exits with code 2, so CI and users can tell a stub
apart from a real success. ``tymi --help`` lists them and exits 0.
"""

from __future__ import annotations

import typer

app = typer.Typer(
    name="tymi",
    help="Fake It Till You Make It — faithful synthetic data + data chaos monkey.",
    no_args_is_help=True,
    add_completion=False,
)

_NOT_IMPLEMENTED_EXIT = 2

_STUB_COMMANDS = {
    "test-connection": "Test a connection to a source/destination engine.",
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


if __name__ == "__main__":  # pragma: no cover
    app()
