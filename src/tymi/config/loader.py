"""YAML config loader with schema-version gating (AD-5)."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from tymi.config.models import SUPPORTED_SCHEMA_MAJOR, Config
from tymi.core.errors import ConfigError, ConfigVersionError


def _major(version: str) -> int:
    try:
        return int(str(version).split(".", 1)[0])
    except (ValueError, AttributeError) as exc:
        raise ConfigVersionError(f"Invalid schema_version: {version!r}") from exc


def load_config(path: str | Path) -> Config:
    """Load and validate a config file.

    Raises ``ConfigError`` on malformed YAML/schema and ``ConfigVersionError``
    when the file's ``schema_version`` major is not supported.
    """
    text = Path(path).read_text(encoding="utf-8")
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"Could not parse YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError("Config root must be a mapping.")

    declared = data.get("schema_version", "1.0.0")
    if _major(declared) != SUPPORTED_SCHEMA_MAJOR:
        raise ConfigVersionError(
            f"Unsupported config schema_version {declared!r}; "
            f"this build supports major {SUPPORTED_SCHEMA_MAJOR}."
        )

    try:
        return Config(**data)
    except ValidationError as exc:
        raise ConfigError(f"Invalid config: {exc}") from exc
