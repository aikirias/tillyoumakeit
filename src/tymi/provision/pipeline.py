"""The one whole-DB provisioning pipeline (AD-19).

``provision`` is the thin composition adapter the CLI command and any external DAG/CI job call
**identically** (AD-19): destination guardrail (AD-18) → whole-DB generate (per-table LeakageGate,
substreams, shared keys, fixtures overlay + scan-and-reject → ``GatedDataset``, AD-13/16/17/20/21)
→ ``require_gated`` at the load boundary → ``EngineAdapter.load`` → provisioning report with the
consistency-unit fingerprint (AD-15, PDE-15). Scheduling and retries stay in the external
orchestrator — this pipeline runs once, in-process.

The guardrail runs **first** so a production destination fails closed before any generation or
write happens (a stronger "before any write" than the flow's minimum). The **caller** must build
``adapter`` to target the Spec's affirmed destination — the CLI cross-checks its ``--config``
connection against ``spec.destination`` before calling this.

**Idempotency (NFR-F):** each table is loaded with a clean-replace (``if_exists="replace"``), so a
re-run overwrites rather than appends — a failed run **self-heals on re-run**. Loads are *per-table*
transactions, not one whole-DB transaction: a mid-run failure can leave earlier tables written and
later ones stale, which a re-run corrects. Whole-DB atomicity is out of the in-memory Phase-1 scope.
"""

from __future__ import annotations

from dataclasses import dataclass

from tymi.config.consistency import consistency_fingerprint
from tymi.config.spec import Spec, spec_profiles
from tymi.core.errors import EngineError
from tymi.domain.artifacts import Dataset, require_gated
from tymi.eval.fidelity import fidelity_report
from tymi.provision.guardrail import DEFAULT_PROD_DENY_LIST, assert_nonprod_destination
from tymi.synth.whole_db import generate_from_spec


@dataclass(frozen=True)
class TableProvisionReport:
    """Per-table line of the provisioning report (PDE-15)."""

    table: str
    rows: int
    fixtures: int
    gated_columns: tuple[str, ...]
    fidelity_correlation: float | None
    fidelity_passed: bool


@dataclass(frozen=True)
class ProvisionReport:
    """The provisioning report (PDE-15): what was provisioned + the consistency fingerprint."""

    fingerprint: str
    environment: str
    tables: tuple[TableProvisionReport, ...]

    def render(self) -> str:
        """A human-readable rendering for the CLI/DAG log."""
        lines = [
            f"Provisioned {len(self.tables)} table(s) to a '{self.environment}' destination.",
            f"Consistency-unit fingerprint: {self.fingerprint}",
        ]
        for t in self.tables:
            corr = "n/a" if t.fidelity_correlation is None else f"{t.fidelity_correlation:.3f}"
            fixtures = f", fixtures={t.fixtures}" if t.fixtures else ""
            lines.append(
                f"  - {t.table}: rows={t.rows}{fixtures}, "
                f"gated_columns={list(t.gated_columns)}, "
                f"fidelity(correlation={corr}, passed={t.fidelity_passed})"
            )
        return "\n".join(lines)


def provision(
    spec: Spec,
    adapter: object,
    *,
    deny_list: tuple[str, ...] = DEFAULT_PROD_DENY_LIST,
    deps: dict[str, str] | None = None,
) -> ProvisionReport:
    """Provision the whole obfuscated DB described by ``spec`` into ``adapter`` (AD-19).

    ``adapter`` is a destination :class:`~tymi.ports.EngineAdapter` (built by the caller with the
    runner's credentials; secrets never live in the Spec). Fails closed via
    :class:`~tymi.core.errors.GuardrailError` on a production destination **before** any generation
    or write. Only a :class:`~tymi.domain.artifacts.GatedDataset` is ever loaded (AD-21).
    """
    assert_nonprod_destination(spec.destination, deny_list=deny_list)
    if not getattr(adapter, "supports_write", False):
        raise EngineError("destination adapter does not support write; cannot provision.")

    gated = generate_from_spec(spec)
    profiles = spec_profiles(spec)
    table_reports: list[TableProvisionReport] = []
    for name, gated_dataset in gated.items():
        checked = require_gated(gated_dataset)  # AD-21 type gate at the load call site
        adapter.load(checked.dataset, table=name)  # per-table clean-replace (idempotent, NFR-F)
        # Score fidelity on the faithfully-generated columns only: shared-key columns are
        # position-derived and intentionally diverge from the source, so including them would
        # depress the score misleadingly.
        shared = spec.tables[name].shared_keys
        scored = Dataset(
            frame=checked.frame.drop(columns=shared, errors="ignore"), schema=checked.schema
        )
        fidelity = fidelity_report(profiles[name], scored, tolerance=spec.tolerance)
        table_reports.append(
            TableProvisionReport(
                table=name,
                rows=len(checked.frame),
                fixtures=len(spec.tables[name].fixtures),
                gated_columns=checked.report.columns_checked,
                fidelity_correlation=fidelity.global_correlation,
                fidelity_passed=fidelity.passed,
            )
        )

    return ProvisionReport(
        fingerprint=consistency_fingerprint(spec, deps=deps),
        environment=spec.destination.environment,
        tables=tuple(table_reports),
    )
