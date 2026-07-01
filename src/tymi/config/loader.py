"""YAML config loader with schema-version gating (AD-5)."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from tymi.config.models import SUPPORTED_SCHEMA_MAJOR, Config
from tymi.core.errors import ConfigError, ConfigVersionError


def _major(version: str) -> int:
    """Parse the major component of a version string.

    Raises ``ConfigVersionError`` when the value has no integer major.
    """
    try:
        return int(version.split(".", 1)[0])
    except (ValueError, TypeError) as exc:
        raise ConfigVersionError(f"Invalid schema_version: {version!r}") from exc


def load_config(path: str | Path) -> Config:
    """Load and validate a config file.

    Raises ``ConfigVersionError`` when the file's ``schema_version`` major is not
    supported (or is malformed), and ``ConfigError`` on any other malformed
    YAML/schema (including unknown keys or out-of-range values).
    """
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigError(f"Could not read config file {path}: {exc}") from exc
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"Could not parse YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError("Config root must be a mapping.")

    # Version gating first, and independent of type: YAML may load the value as
    # an int/float (e.g. `schema_version: 1.0`); normalise to a string so a
    # malformed version is reported as a version error, not a schema error.
    declared = str(data.get("schema_version", "1.0.0"))
    if _major(declared) != SUPPORTED_SCHEMA_MAJOR:
        raise ConfigVersionError(
            f"Unsupported config schema_version {declared!r}; "
            f"this build supports major {SUPPORTED_SCHEMA_MAJOR}."
        )
    data = {**data, "schema_version": declared}

    try:
        return Config(**data)
    except ValidationError as exc:
        raise ConfigError(f"Invalid config: {exc}") from exc
