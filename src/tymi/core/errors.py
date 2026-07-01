"""Typed error hierarchy. Every error TYMI raises subclasses ``TymiError``."""

from __future__ import annotations


class TymiError(Exception):
    """Base class for all TYMI errors."""


class ConfigError(TymiError):
    """Configuration is invalid or cannot be loaded."""


class ConfigVersionError(ConfigError):
    """The config file's ``schema_version`` major is not supported."""


class EngineError(TymiError):
    """A source/destination engine adapter failed."""


class EngineConnectionError(EngineError):
    """Could not connect to an engine (bad credentials, host unreachable, …).

    Messages must never contain secret values (NFR-6).
    """


class TableNotFoundError(EngineError):
    """The requested table does not exist in the source."""
