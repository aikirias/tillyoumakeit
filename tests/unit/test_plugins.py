"""AC-6 (Story 1.1): the plugin registry loads entry-point groups cleanly.

The ``tymi.engines`` group has the engine adapters (asserted in
``test_engine_registration.py``); ``tymi.mutators`` has the out-of-distribution
(Story 3.2) and format/type violation (Story 3.3) fault mutators.
"""

from __future__ import annotations

from tymi.chaos.mutators.outlier import OutlierMutator
from tymi.core.plugins import load_mutators, load_plugins

_EXPECTED_MUTATORS = {
    "outlier",
    "text_in_numeric",
    "invalid_date",
    "broken_encoding",
    "oversized_string",
    "illegal_null",
    "missing_field",
    "extra_field",
    "renamed_column",
    "changed_type",
    "duplicate_keys",
    "orphan_fk",
}


def test_expected_mutators_registered() -> None:
    assert _EXPECTED_MUTATORS <= set(load_mutators())
    assert load_mutators().get("outlier") is OutlierMutator


def test_unknown_group_is_empty() -> None:
    assert load_plugins("tymi.does-not-exist") == {}
