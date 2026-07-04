"""Typed error hierarchy. Every error TYMI raises subclasses ``TymiError``."""

from __future__ import annotations


class TymiError(Exception):
    """Base class for all TYMI errors."""


class ConfigError(TymiError):
    """Configuration is invalid or cannot be loaded."""


class ConfigVersionError(ConfigError):
    """The config file's ``schema_version`` major is not supported."""


class ProfileError(TymiError):
    """A saved Profile artifact is unreadable or malformed."""


class ProfileVersionError(ProfileError):
    """A saved Profile's ``schema_version`` major is not supported."""


class GenerationError(TymiError):
    """Synthetic generation cannot satisfy the request (e.g. a cyclic FK graph)."""


class LeakageError(TymiError):
    """The leakage gate could not keep a real sensitive value out of the output.

    Raised when a colliding value in a Sensitive Column cannot be regenerated away
    within the attempt budget; the run **fails closed** rather than emit a real
    value (NFR-1, AD-7).
    """


class ExportError(TymiError):
    """A Dataset could not be exported (unknown format, unwritable target, …)."""


class ChaosError(TymiError):
    """A chaos run cannot proceed (unknown Mutator, a Mutator off its contract, a bad
    chaos policy, …). Repeating a Mutator in the chain is allowed (faults may stack)."""


class EngineError(TymiError):
    """A source/destination engine adapter failed."""


class EngineConnectionError(EngineError):
    """Could not connect to an engine (bad credentials, host unreachable, …).

    Messages must never contain secret values (NFR-6).
    """


class TableNotFoundError(EngineError):
    """The requested table does not exist in the source."""
