"""AC-3: config loads from YAML; unknown major schema_version is rejected."""

from __future__ import annotations

from pathlib import Path

import pytest

from tymi.config import load_config
from tymi.core.errors import ConfigError, ConfigVersionError


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_valid_config_loads(tmp_path: Path) -> None:
    cfg = load_config(_write(tmp_path, "schema_version: '1.2.0'\nseed: 7\n"))
    assert cfg.schema_version == "1.2.0"
    assert cfg.seed == 7


def test_defaults_apply_for_empty_config(tmp_path: Path) -> None:
    cfg = load_config(_write(tmp_path, "{}\n"))
    assert cfg.schema_version == "1.0.0"
    assert cfg.generation.tolerance == 0.9


def test_unknown_major_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigVersionError):
        load_config(_write(tmp_path, "schema_version: '2.0.0'\n"))


def test_non_string_version_gated_as_version_error(tmp_path: Path) -> None:
    # YAML loads `2` as an int; it must still be a *version* error, not a
    # generic schema error, and a supported major given as int must load.
    with pytest.raises(ConfigVersionError):
        load_config(_write(tmp_path, "schema_version: 2\n"))
    cfg = load_config(_write(tmp_path, "schema_version: 1\n"))
    assert cfg.schema_version == "1"


def test_malformed_version_is_version_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigVersionError):
        load_config(_write(tmp_path, "schema_version: abc\n"))


def test_unknown_key_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_config(_write(tmp_path, "choas: {}\n"))


def test_out_of_range_values_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_config(_write(tmp_path, "generation:\n  tolerance: 5.0\n"))
    with pytest.raises(ConfigError):
        load_config(_write(tmp_path, "chaos:\n  rate: -1.0\n"))


def test_malformed_root_is_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_config(_write(tmp_path, "- just\n- a\n- list\n"))
