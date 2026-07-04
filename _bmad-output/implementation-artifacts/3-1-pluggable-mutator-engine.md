---
baseline_commit: b9b4b8c
---

# Story 3.1: Pluggable Mutator engine

Status: done

## Story

As a developer,
I want a Mutator port and pipeline stage with entry-point discovery,
so that new fault types can be added without touching the core.

## Acceptance Criteria

1. **Entry-point discovery** — Mutators registered under the `tymi.mutators`
   entry-point group (AD-3) are resolved by name via `load_mutators()`; the chaos
   engine never imports a concrete mutator. An unknown name raises a typed
   `ChaosError` (never a bare `KeyError`).
2. **Configurable order** — the engine runs the resolved Mutators in the exact order
   declared (a `ChaosConfig.mutators` list of names); the order is observable in the
   merged manifest.
3. **Each Mutator records what it corrupted** — every Mutator returns a
   `(Dataset, FaultManifest)`; the engine threads the mutated Dataset into the next
   Mutator and **merges** the manifests into one, preserving order.
4. **Shared RNG (AD-4/AD-11)** — the engine passes the one injected
   `numpy.random.Generator` to every Mutator's `apply(dataset, *, rng)`; the same
   seed + mutator chain yields identical output and manifest.
5. **Zero core changes for a new Mutator** — adding a Mutator to the registry (not to
   the engine) is enough for it to run; proven by discovering and running a Mutator
   the engine has never heard of.
6. **Canonical artifacts (AD-10)** — each stage consumes/produces a `Dataset`
   (DataFrame + Schema); the engine preserves the Schema unless a Mutator changes it
   (schema faults land in Story 3.4). No fault mutators ship here — the fault
   families are Stories 3.2–3.4; this story is the engine + port + discovery only.

## Tasks / Subtasks

- [ ] **Task 1: Manifest merge** (`src/tymi/domain/artifacts.py`) — a
  `merge_fault_manifests(...)` helper (concatenate entries, order-preserving) +
  `fault_manifest_to_json`.
- [ ] **Task 2: Typed error + config** (`src/tymi/core/errors.py`,
  `src/tymi/config/models.py`) — `ChaosError(TymiError)`; `ChaosConfig.mutators:
  list[str]` (ordered names).
- [ ] **Task 3: Chaos engine** (`src/tymi/chaos/engine.py`) —
  `resolve_mutators(names, *, registry=None) -> list[Mutator]` (name→instance via
  `load_mutators()`; unknown → `ChaosError`) and `apply_chaos(dataset, mutators, *,
  rng) -> tuple[Dataset, FaultManifest]` (run in order, thread Dataset + rng, merge
  manifests).
- [ ] **Task 4: Unit tests** — ordering (via manifest), rng threading + determinism,
  manifest merge, entry-point discovery (monkeypatched registry), unknown-name error,
  a never-before-seen Mutator runs with zero engine changes, Protocol conformance.
- [ ] **Task 5: Full 3-layer `bmad-code-review` gate** before marking done.

## Dev Notes

- **Discovery, not import.** The engine resolves mutators from the `tymi.mutators`
  registry (`core.plugins.load_mutators`) by the names/order in `ChaosConfig`. It has
  no knowledge of any concrete mutator, so Stories 3.2–3.4 add fault families purely
  by registering entry points — the "zero core changes" AC. Tests inject a registry
  (or monkeypatch `load_mutators`) with test-double mutators, exactly as a future real
  mutator would be discovered.
- **RNG threading (AD-4/AD-11).** One Generator is threaded to every Mutator in the
  chain (not a fresh one per mutator), so the whole chaos run is reproducible from a
  single seed. Each Mutator draws from it; the order of mutators therefore affects the
  draw sequence — which is why the order is part of the Config and the manifest.
- **Manifest is the audit contract (previews Story 3.6).** Each Mutator records its
  corruptions as manifest entries; the engine merges them so a downstream Evaluate
  (chaos run_mode, AD-12) can validate the bidirectional fault contract. This story
  ships the merge; the full bidirectional validation is Story 3.6.
- **Scope.** Library engine only — no `tymi chaos` CLI yet (that lands with the Chaos
  Policy, Story 3.5, which adds rate/targeting/mode). The AD-7 leakage gate on the
  chaos branch is an orchestrator concern (both branches gated) and travels with the
  pipeline wiring. No fault mutators here.

### References

- [Source: epics.md#Epic-3 Story 3.1; FR-11]
- [Source: ARCHITECTURE-SPINE.md — AD-3 (entry-point discovery), AD-4/AD-11 (RNG),
  AD-8 (chaos stage in the core pipeline), AD-10 (canonical Dataset), AD-12 (Evaluate
  chaos run_mode validates the manifest)]
- [Source: ports/__init__.py — `Mutator` Protocol (`apply(dataset, *, rng) ->
  (Dataset, FaultManifest)`)]
- [Source: core/plugins.py — `load_mutators` / `MUTATORS_GROUP`]

## Dev Agent Record

### Agent Model Used

Claude Opus 4.8 (claude-opus-4-8)

### Debug Log References

- All tests run **inside the devcontainer** (`devcontainer exec`): `uv run ruff check
  .` / `uv run lint-imports` → clean (2 contracts kept); `uv run pytest tests/unit` →
  292 passed. No new dependency.

### Completion Notes List

- Chaos engine (`chaos/engine.py`): `resolve_mutators` discovers Mutators from the
  `tymi.mutators` entry-point group by name+order (AD-3), `apply_chaos` runs the chain
  threading the shared `rng` (AD-4/AD-11) and the mutated Dataset, and merges each
  Mutator's `FaultManifest`. No fault mutators ship here (Stories 3.2–3.4); no CLI
  (Story 3.5).
- **Full 3-layer `bmad-code-review` gate** (Blind + Edge Case + Acceptance). No HIGH
  correctness bug in the metric/plumbing logic; hardened the Mutator interface
  boundary against the review's robustness findings: a Mutator that returns anything
  other than a `(Dataset, FaultManifest)` pair (bare Dataset, 3-tuple, `(None, …)`)
  now raises `ChaosError` naming it instead of a cryptic unpack/attribute error in a
  different module; a registry entry that is not an instantiable factory (an instance,
  or a class that raises in `__init__`) raises `ChaosError`; and the engine now works
  on a **copy** of the caller's frame so a contract-violating in-place Mutator cannot
  corrupt the input and re-runs are idempotent. Corrected the `ChaosError` docstring
  (repeating a Mutator is allowed — faults may stack). Closed the Acceptance Auditor's
  test-strength gaps: merged-manifest order on a reversed chain, a following Mutator
  observing the previous one's mutation, Schema preservation (AD-10), and a
  `fault_type` fixture anchoring the manifest convention for Story 3.6. +8 tests → 292
  unit. All 6 ACs satisfied.

### File List

- `src/tymi/chaos/engine.py` (new — `resolve_mutators`, `apply_chaos`)
- `src/tymi/domain/artifacts.py` (modified — `merge_fault_manifests`,
  `fault_manifest_to_json`, FaultManifest docstring)
- `src/tymi/core/errors.py` (modified — `ChaosError`)
- `src/tymi/config/models.py` (modified — `ChaosConfig.mutators`)
- `tests/unit/test_chaos_engine.py` (new)
- `docs/status.md` (modified)

## Change Log

| Date | Change |
| --- | --- |
| 2026-07-04 | Implemented Story 3.1 — pluggable Mutator engine. `chaos/engine.py` (`resolve_mutators` entry-point discovery + ordered chain, `apply_chaos` threading the shared RNG + Dataset, merged `FaultManifest`); `merge_fault_manifests`/`fault_manifest_to_json`; `ChaosError`; `ChaosConfig.mutators`. No fault mutators / no CLI (later stories). |
| 2026-07-04 | Full 3-layer `bmad-code-review` gate. Hardened the Mutator interface boundary (off-contract returns / uninstantiable registry entries → `ChaosError` naming the mutator; defensive frame copy so an in-place Mutator can't corrupt the caller and re-runs are idempotent); fixed the `ChaosError` docstring (duplicates allowed). Closed reversed-order / next-sees-mutation / Schema-preservation / `fault_type`-fixture test gaps. 292 unit. All 6 ACs satisfied. Status → done. |
| 2026-07-04 | Second-pass verification (the late Blind Hunter re-reviewed the committed code; core claims — RNG threading, defensive copy, off-contract handling — confirmed solid). Closed 2 residual findings: a wrong-arity `apply` passed `isinstance` (a `runtime_checkable` Protocol checks member presence only) and would crash mid-chain with a raw `TypeError` → now `resolve_mutators` bind-checks the `apply` signature up front and raises `ChaosError`; `merge_fault_manifests` aliased the source entry dicts → now shallow-copies each entry. Documented that the frame copy cannot defend against in-place mutation of a mutable object stored *inside* a cell (an AD-10 contract violation, empirically confirmed, near-unreachable in the scalar pipeline). +3 tests → 295 unit. |
