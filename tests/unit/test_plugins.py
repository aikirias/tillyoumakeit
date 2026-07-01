"""AC-6: the plugin registry loads entry-point groups and is empty by default."""

from __future__ import annotations

from tymi.core.plugins import load_engines, load_mutators, load_plugins


def test_registry_empty_when_no_plugins() -> None:
    assert load_engines() == {}
    assert load_mutators() == {}


def test_unknown_group_is_empty() -> None:
    assert load_plugins("tymi.does-not-exist") == {}
