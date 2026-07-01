"""Config models (AD-5).

The whole run is described by one ``Config`` loaded from YAML. It carries a
semver ``schema_version``; the loader rejects an unknown major version.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

#: The config schema major version this build understands.
SUPPORTED_SCHEMA_MAJOR = 1


class SourceConfig(BaseModel):
    """Where to read from (placeholder; filled in later stories)."""

    engine: str | None = None
    table: str | None = None


class GenerationConfig(BaseModel):
    """Faithful-generation settings (placeholder)."""

    rows: int | None = None
    tolerance: float = 0.9


class ChaosConfig(BaseModel):
    """Chaos-policy settings (placeholder)."""

    rate: float = 0.0


class Config(BaseModel):
    """Top-level declarative config."""

    schema_version: str = "1.0.0"
    seed: int | None = None
    source: SourceConfig = Field(default_factory=SourceConfig)
    generation: GenerationConfig = Field(default_factory=GenerationConfig)
    chaos: ChaosConfig = Field(default_factory=ChaosConfig)
