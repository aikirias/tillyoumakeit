"""Typed error hierarchy. Every error TYMI raises subclasses ``TymiError``."""

from __future__ import annotations


class TymiError(Exception):
    """Base class for all TYMI errors."""


class ConfigError(TymiError):
    """Configuration is invalid or cannot be loaded."""


class ConfigVersionError(ConfigError):
    """The config file's ``schema_version`` major is not supported."""
