"""AC-2: the hexagonal dependency direction is enforced by import-linter.

Runs the same contracts CI runs. Skips only if the tool is unavailable in the
environment (CI runs `lint-imports` directly as a hard gate regardless).
"""

from __future__ import annotations

import shutil
import subprocess

import pytest


def test_import_contracts_pass() -> None:
    exe = shutil.which("lint-imports")
    if exe is None:  # pragma: no cover - only when dev deps are absent
        pytest.skip("import-linter (lint-imports) not installed")
    result = subprocess.run([exe], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
