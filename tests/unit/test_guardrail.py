"""PRD 1 Story 3.2: non-production destination guardrail (AD-18, closes OQ-2)."""

from __future__ import annotations

import pytest

from tymi.config.consistency import consistency_fingerprint
from tymi.config.spec import DestinationSpec, Spec, bootstrap_spec
from tymi.core.errors import GuardrailError
from tymi.provision.guardrail import (
    DEFAULT_PROD_DENY_LIST,
    NONPROD,
    assert_nonprod_destination,
)

_FIXED_DEPS = {"tymi": "1.0.0", "numpy": "2.0.0", "pandas": "2.0.0", "faker": "1.0.0"}


# --- affirmation (fail-closed default) --------------------------------------


def test_accepts_a_nonprod_destination_not_on_the_deny_list() -> None:
    dest = DestinationSpec(environment=NONPROD, host="dev-db.internal", database="app_dev")
    assert_nonprod_destination(dest)  # does not raise


def test_missing_destination_fails_closed() -> None:
    with pytest.raises(GuardrailError, match="requires a destination block"):
        assert_nonprod_destination(None)


def test_non_nonprod_environment_fails_closed() -> None:
    dest = DestinationSpec(environment="staging", host="dev-db", database="app")
    with pytest.raises(GuardrailError, match="must affirm environment"):
        assert_nonprod_destination(dest)


def test_affirmation_is_case_sensitive_and_fails_closed() -> None:
    # The affirmation is an exact "nonprod"; a case/whitespace variant fails in the safe direction.
    for variant in ("NONPROD", "NonProd", " nonprod", "nonprod "):
        dest = DestinationSpec(environment=variant, host="dev", database="a")
        with pytest.raises(GuardrailError, match="must affirm environment"):
            assert_nonprod_destination(dest)


def test_nonprod_affirmation_with_no_identifiers_passes() -> None:
    # host/database are optional; an affirmed nonprod target with neither still passes (the
    # affirmation is the primary gate — there is simply nothing for the deny-list to match).
    assert_nonprod_destination(DestinationSpec(environment=NONPROD))


# --- prod deny-list ---------------------------------------------------------


def test_deny_list_match_on_host_fails_closed() -> None:
    dest = DestinationSpec(environment=NONPROD, host="prod-db-01.internal", database="app")
    with pytest.raises(GuardrailError, match="deny-list pattern"):
        assert_nonprod_destination(dest)


def test_deny_list_match_on_database_fails_closed() -> None:
    dest = DestinationSpec(environment=NONPROD, host="db01", database="production_main")
    with pytest.raises(GuardrailError, match="deny-list pattern"):
        assert_nonprod_destination(dest)


def test_deny_list_is_case_insensitive() -> None:
    dest = DestinationSpec(environment=NONPROD, host="PROD-Cluster", database="app")
    with pytest.raises(GuardrailError, match="deny-list pattern"):
        assert_nonprod_destination(dest)


def test_empty_deny_list_still_requires_the_affirmation() -> None:
    # An empty deny-list never means "allow all": the affirmation is still required.
    bad = DestinationSpec(environment="prod", host="prod-db", database="app")
    with pytest.raises(GuardrailError, match="must affirm environment"):
        assert_nonprod_destination(bad, deny_list=())
    # ...and a properly-affirmed nonprod target passes even a prod-named host when the deny-list
    # is empty (the deployment chose to trust the affirmation).
    ok = DestinationSpec(environment=NONPROD, host="prod-lookalike", database="app")
    assert_nonprod_destination(ok, deny_list=())


def test_custom_deny_list_overrides_default() -> None:
    dest = DestinationSpec(environment=NONPROD, host="live-cluster", database="app")
    with pytest.raises(GuardrailError, match="deny-list pattern"):
        assert_nonprod_destination(dest, deny_list=("*live*",))
    assert "*prod*" in DEFAULT_PROD_DENY_LIST  # the documented default


# --- destination is excluded from the consistency fingerprint ---------------


def test_destination_does_not_change_the_consistency_fingerprint() -> None:
    base = bootstrap_spec({}, seed=0)
    with_dest = bootstrap_spec({}, seed=0)
    with_dest.destination = DestinationSpec(environment=NONPROD, host="dev", database="app")
    assert consistency_fingerprint(base, deps=_FIXED_DEPS) == consistency_fingerprint(
        with_dest, deps=_FIXED_DEPS
    )


def test_destination_round_trips_and_forbids_extra_keys() -> None:
    spec = Spec(destination=DestinationSpec(environment=NONPROD, host="h", database="d"))
    assert spec.destination.environment == NONPROD
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        DestinationSpec.model_validate({"environment": NONPROD, "bogus": 1})
