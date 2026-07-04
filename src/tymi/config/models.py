"""Config models (AD-5).

The whole run is described by one ``Config`` loaded from YAML. It carries a
semver ``schema_version``; the loader rejects an unknown major version. Every
model forbids unknown keys so typos fail loudly rather than being dropped.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

#: The config schema major version this build understands.
SUPPORTED_SCHEMA_MAJOR = 1

_FORBID_EXTRA = ConfigDict(extra="forbid")


class ConnectionConfig(BaseModel):
    """Non-secret connection settings for an engine.

    Credentials are never stored here (NFR-6): only the *names* of the
    environment variables that hold the username and password. Defaults target
    MSSQL / ODBC Driver 18 (encryption on, trust self-signed certs so local test
    containers work).
    """

    model_config = _FORBID_EXTRA

    host: str
    port: int | None = Field(default=None, gt=0, le=65535)
    database: str | None = None
    # MSSQL/ODBC-only options; ignored by other engines.
    driver: str | None = None
    encrypt: bool = True
    trust_server_certificate: bool = True
    user_env: str = "TYMI_DB_USER"
    password_env: str = "TYMI_DB_PASSWORD"


class SourceConfig(BaseModel):
    """Where to read from (placeholder; filled in later stories)."""

    model_config = _FORBID_EXTRA

    engine: str | None = None
    table: str | None = None
    connection: ConnectionConfig | None = None
    #: Columns whose real values must never leak into faithful output (AR-7).
    #: The profiler stores only a hashed membership set of these columns' values
    #: (AD-6/AD-7); the leakage gate checks generated values against it.
    sensitive_columns: list[str] = Field(default_factory=list)


class GenerationConfig(BaseModel):
    """Faithful-generation settings (placeholder)."""

    model_config = _FORBID_EXTRA

    rows: int | None = Field(default=None, gt=0)
    tolerance: float = Field(default=0.9, ge=0.0, le=1.0)


class ChaosConfig(BaseModel):
    """Chaos-policy settings (placeholder)."""

    model_config = _FORBID_EXTRA

    rate: float = Field(default=0.0, ge=0.0, le=1.0)


class Config(BaseModel):
    """Top-level declarative config."""

    model_config = _FORBID_EXTRA

    schema_version: str = "1.0.0"
    seed: int | None = None
    source: SourceConfig = Field(default_factory=SourceConfig)
    generation: GenerationConfig = Field(default_factory=GenerationConfig)
    chaos: ChaosConfig = Field(default_factory=ChaosConfig)
