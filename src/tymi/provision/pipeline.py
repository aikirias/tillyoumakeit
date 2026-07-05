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
from itertools import groupby

from tymi.config.consistency import consistency_fingerprint
from tymi.config.spec import Spec, spec_profiles
from tymi.core.errors import EngineError
from tymi.domain.artifacts import Dataset, require_gated
from tymi.eval.fidelity import fidelity_report
from tymi.provision.guardrail import DEFAULT_PROD_DENY_LIST, assert_nonprod_destination
from tymi.synth.streaming import stream_from_spec
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
    stream: bool = False,
) -> ProvisionReport:
    """Provision the whole obfuscated DB described by ``spec`` into ``adapter`` (AD-19).

    ``adapter`` is a destination :class:`~tymi.ports.EngineAdapter` (built by the caller with the
    runner's credentials; secrets never live in the Spec). Fails closed via
    :class:`~tymi.core.errors.GuardrailError` on a production destination **before** any generation
    or write. Only a :class:`~tymi.domain.artifacts.GatedDataset` is ever loaded (AD-21).

    With ``stream=True`` (Phase 2, AD-22..24) the DB is generated and written **chunk by chunk**, so
    peak memory is one chunk regardless of the DB's size — for provisioning arbitrarily large
    databases. Streaming does not overlay pinned fixtures (fails closed); use the default in-memory
    path for a DB with fixtures.
    """
    assert_nonprod_destination(spec.destination, deny_list=deny_list)
    if not getattr(adapter, "supports_write", False):
        raise EngineError("destination adapter does not support write; cannot provision.")

    tables = (
        _provision_streaming(spec, adapter) if stream else _provision_in_memory(spec, adapter)
    )
    return ProvisionReport(
        fingerprint=consistency_fingerprint(
            spec, deps=deps, mode="streaming" if stream else "in_memory"
        ),
        environment=spec.destination.environment,
        tables=tuple(tables),
    )


def _provision_in_memory(spec: Spec, adapter: object) -> list[TableProvisionReport]:
    """The Phase-1 path: generate the whole DB in memory, then clean-replace each table."""
    gated = generate_from_spec(spec)
    profiles = spec_profiles(spec)
    reports: list[TableProvisionReport] = []
    for name, gated_dataset in gated.items():
        checked = require_gated(gated_dataset)  # AD-21 type gate at the load call site
        adapter.load(checked.dataset, table=name)  # per-table clean-replace (idempotent, NFR-F)
        reports.append(
            _table_report(
                spec, profiles[name], name, checked.frame,
                checked.report.columns_checked, len(spec.tables[name].fixtures),
            )
        )
    return reports


@dataclass
class _StreamState:
    """Mutable per-table accumulator filled while ``load_stream`` consumes the chunk generator."""

    rows: int = 0
    first: object = None
    gated_columns: tuple[str, ...] = ()


def _require_gated_chunks(group, state: _StreamState):
    """Yield each chunk's sealed Dataset, enforcing AD-21 and recording report state as we go."""
    for chunk in group:
        gated = require_gated(chunk.gated)  # AD-21 at the write boundary
        state.rows += len(gated.frame)
        if state.first is None:
            state.first = gated.frame
            state.gated_columns = gated.report.columns_checked
        yield gated.dataset


def _provision_streaming(spec: Spec, adapter: object) -> list[TableProvisionReport]:
    """The Phase-2 out-of-core path: stream each table chunk-by-chunk into ``load_stream``.

    ``stream_from_spec`` yields sealed chunks in FK-topological order; each is ``require_gated``
    (AD-21 at the write boundary) then written. Peak memory is bounded to ~one chunk (the first
    chunk of each table is retained for fidelity scoring); the report aggregates row counts across
    chunks and scores fidelity on that first chunk.
    """
    profiles = spec_profiles(spec)
    reports: list[TableProvisionReport] = []
    for table, group in groupby(stream_from_spec(spec), key=lambda c: c.table):
        state = _StreamState()
        # load_stream synchronously consumes the whole per-table group before we advance, so the
        # groupby sub-iterator is used exactly once (B031 is a false positive here).
        adapter.load_stream(_require_gated_chunks(group, state), table=table)  # noqa: B031
        if state.first is None:  # adapter returned without consuming the chunks — contract breach
            raise EngineError(
                f"adapter.load_stream did not consume the chunks for table {table!r}; "
                "it must write every chunk it is given (AD-24)."
            )
        reports.append(
            _table_report(
                spec, profiles[table], table, state.first, state.gated_columns, 0,
                total_rows=state.rows,
            )
        )
    return reports


def _table_report(
    spec: Spec,
    profile,
    name: str,
    frame,
    gated_columns: tuple[str, ...],
    fixtures: int,
    total_rows: int | None = None,
) -> TableProvisionReport:
    """Build one table's report line, scoring fidelity on ``frame`` (the whole table, or the first
    streamed chunk). Shared-key columns are dropped from the score — they are position-derived and
    intentionally diverge from the source, so including them would depress it misleadingly.
    """
    scored = Dataset(
        frame=frame.drop(columns=spec.tables[name].shared_keys, errors="ignore"),
        schema=profile.schema,
    )
    fidelity = fidelity_report(profile, scored, tolerance=spec.tolerance)
    return TableProvisionReport(
        table=name,
        rows=len(frame) if total_rows is None else total_rows,
        fixtures=fixtures,
        gated_columns=gated_columns,
        fidelity_correlation=fidelity.global_correlation,
        fidelity_passed=fidelity.passed,
    )
