"""AC-1: `tymi --help` exits 0 and lists all subcommands."""

from __future__ import annotations

from typer.testing import CliRunner

from tymi.cli.app import app

runner = CliRunner()

EXPECTED_COMMANDS = [
    "test-connection",
    "schema",
    "sample",
    "profile",
    "generate",
    "chaos",
    "report",
    "ui",
]


def test_help_exits_zero_and_lists_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in EXPECTED_COMMANDS:
        assert command in result.output


def test_ui_is_a_real_command_not_a_stub() -> None:
    # `ui` launches Streamlit (Story 5.1); --help must not spawn the server.
    result = runner.invoke(app, ["ui", "--help"])
    assert result.exit_code == 0
    assert "not implemented" not in result.output
    assert "Streamlit" in result.output
