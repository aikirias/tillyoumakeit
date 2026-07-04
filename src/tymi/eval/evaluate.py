"""Evaluate branch (AD-12).

``evaluate`` consumes a Dataset + ``run_mode`` and discriminates:

- **faithful** → the Story 2.7 :class:`~tymi.domain.artifacts.FidelityReport`
  (requires the source Profile).
- **chaos** → the Story 3.6 :class:`~tymi.domain.artifacts.ManifestAudit`, validating
  the FaultManifest against the faithful ``baseline`` and the chaotic output — **no**
  fidelity report.

The orchestrator sets ``run_mode``; Evaluate never infers it.
"""

from __future__ import annotations

from tymi.domain.artifacts import Dataset, FaultManifest, ManifestAudit, Profile
from tymi.eval.chaos_audit import audit_manifest
from tymi.eval.fidelity import fidelity_report


def evaluate(
    dataset: Dataset,
    *,
    run_mode: str,
    profile: Profile | None = None,
    baseline: Dataset | None = None,
    manifest: FaultManifest | None = None,
    tolerance: float = 0.9,
) -> object:
    """Evaluate ``dataset`` per ``run_mode`` (AD-12): faithful → fidelity, chaos → audit."""
    if run_mode == "faithful":
        if profile is None:
            raise ValueError("faithful run_mode requires the source profile")
        return fidelity_report(profile, dataset, tolerance=tolerance)
    if run_mode == "chaos":
        if baseline is None or manifest is None:
            raise ValueError("chaos run_mode requires the faithful baseline and the manifest")
        return audit_manifest(baseline, dataset, manifest)
    raise ValueError(f"unknown run_mode {run_mode!r}; expected 'faithful' or 'chaos'")


def is_manifest_audit(result: object) -> bool:
    """True when ``result`` is a chaos-mode :class:`ManifestAudit`."""
    return isinstance(result, ManifestAudit)
