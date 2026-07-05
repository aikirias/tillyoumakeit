"""Non-production destination guardrail (AD-18, closes OQ-2).

Provisioning must **fail closed** unless the Spec's ``destination`` block affirms a non-production
target. OQ-2's detection mechanism is fixed here:

- **Affirmation** — the destination must carry an explicit ``environment: "nonprod"``. Anything
  else (including a missing destination) aborts before any write. This is the primary gate; it is
  never optional and never inferred.
- **Prod deny-list** — a configured list of **case-insensitive glob patterns** matched against the
  destination ``host`` and ``database``. A match aborts even when the affirmation is present (a
  belt-and-braces catch for a mis-affirmed prod target). ``DEFAULT_PROD_DENY_LIST`` denies obvious
  ``*prod*`` / ``*production*`` names; a deployment overrides it with its own patterns. Entries are
  **globs, not substrings** — use ``*prod*`` (a bare ``prod`` matches only the exact string
  ``"prod"``, missing ``prod-db-01``).

**Fail-closed default:** an **empty** deny-list never means "allow all" — the affirmation is still
required. The guardrail runs *before* ``EngineAdapter.load``, and only a ``GatedDataset`` (AD-21)
ever reaches the load boundary, so there is no path that writes un-obfuscated data to any target.
"""

from __future__ import annotations

from fnmatch import fnmatch

from tymi.core.errors import GuardrailError

#: The one affirmation value the destination must carry.
NONPROD = "nonprod"

#: The default production deny-list (glob patterns; a deployment overrides it). Never treated as
#: exhaustive — the ``environment: nonprod`` affirmation is the primary, always-required gate.
DEFAULT_PROD_DENY_LIST: tuple[str, ...] = ("*prod*", "*production*")


def assert_nonprod_destination(
    destination: object, *, deny_list: tuple[str, ...] = DEFAULT_PROD_DENY_LIST
) -> None:
    """Fail closed (:class:`GuardrailError`) unless ``destination`` is a safe non-prod target.

    ``destination`` is a :class:`~tymi.config.spec.DestinationSpec` (typed loosely to keep this
    module free of a config import). Raises when it is ``None``, does not affirm
    ``environment: nonprod``, or its host/database matches a prod deny-list pattern.
    """
    if destination is None:
        raise GuardrailError(
            "provisioning requires a destination block affirming environment: 'nonprod'; "
            "none is present — fail closed (AD-18)."
        )
    if getattr(destination, "environment", None) != NONPROD:
        raise GuardrailError(
            f"destination must affirm environment: {NONPROD!r}, got "
            f"{getattr(destination, 'environment', None)!r}; fail closed (AD-18)."
        )
    for label, target in (("host", destination.host), ("database", destination.database)):
        if target is None:
            continue
        lowered = str(target).lower()
        for pattern in deny_list:
            if fnmatch(lowered, pattern.lower()):
                raise GuardrailError(
                    f"destination {label} {target!r} matches prod deny-list pattern {pattern!r}; "
                    "fail closed (AD-18)."
                )
