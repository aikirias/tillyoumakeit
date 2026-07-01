"""Declarative configuration: Pydantic models + YAML loader (AD-5)."""

from tymi.config.loader import load_config
from tymi.config.models import Config

__all__ = ["Config", "load_config"]
