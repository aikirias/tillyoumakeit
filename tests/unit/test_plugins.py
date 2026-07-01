"""AC-6 (Story 1.1): the plugin registry loads entry-point groups cleanly.

The ``tymi.engines`` group now has the MSSQL adapter (asserted in
``test_engine_registration.py``); ``tymi.mutators`` is still empty.
"""

from __future__ import annotations

from tymi.core.plugins import load_mutators, load_plugins


def test_mutators_registry_empty() -> None:
    assert load_mutators() == {}


def test_unknown_group_is_empty() -> None:
    assert load_plugins("tymi.does-not-exist") == {}
