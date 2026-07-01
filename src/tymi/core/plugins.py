"""Plugin registry (AD-3).

Engines and mutators are discovered via ``importlib.metadata`` entry points
(groups ``tymi.engines`` and ``tymi.mutators``). The core never imports a
concrete adapter directly. When nothing is installed, the registry is empty.
"""

from __future__ import annotations

from importlib import metadata
from typing import Any

ENGINES_GROUP = "tymi.engines"
MUTATORS_GROUP = "tymi.mutators"


def load_plugins(group: str) -> dict[str, Any]:
    """Return ``{entry_point_name: loaded_object}`` for the given group.

    Returns an empty dict when no plugins are registered.
    """
    return {ep.name: ep.load() for ep in metadata.entry_points(group=group)}


def load_engines() -> dict[str, Any]:
    return load_plugins(ENGINES_GROUP)


def load_mutators() -> dict[str, Any]:
    return load_plugins(MUTATORS_GROUP)
