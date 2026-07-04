"""AC-6 (Story 1.1): the plugin registry loads entry-point groups cleanly.

The ``tymi.engines`` group has the engine adapters (asserted in
``test_engine_registration.py``); ``tymi.mutators`` has the ``outlier`` fault
mutator since Story 3.2.
"""

from __future__ import annotations

from tymi.chaos.mutators.outlier import OutlierMutator
from tymi.core.plugins import load_mutators, load_plugins


def test_outlier_mutator_registered() -> None:
    assert load_mutators().get("outlier") is OutlierMutator


def test_unknown_group_is_empty() -> None:
    assert load_plugins("tymi.does-not-exist") == {}
