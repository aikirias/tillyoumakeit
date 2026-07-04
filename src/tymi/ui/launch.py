"""Launch the Streamlit UI as a subprocess (Story 5.1).

`tymi ui` shells out to ``streamlit run`` on :mod:`tymi.ui.app`. The command is built by a
pure, testable function; only the actual process spawn is side-effecting.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

#: The Streamlit entry-point script Streamlit executes.
APP_PATH = Path(__file__).with_name("app.py")


def build_ui_command(*, app_path: Path | None = None, port: int = 8501) -> list[str]:
    """The ``streamlit run`` argv for the app — pure, so it can be asserted in tests."""
    target = app_path if app_path is not None else APP_PATH
    return [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(target),
        "--server.port",
        str(port),
    ]


def launch_ui(*, port: int = 8501) -> int:
    """Run the Streamlit app, returning its exit code (blocks until the server stops)."""
    return subprocess.run(build_ui_command(port=port), check=False).returncode
