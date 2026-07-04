---
baseline_commit: 9cc4c06
---

# Story 3.3: Format and type violation mutators

Status: done

## Story

As a user,
I want to inject malformed formats and wrong types,
so that I can test my parsers and validators.

## Acceptance Criteria

1. **Five independently-toggleable faults** — a mutator per fault, each registered
   under `tymi.mutators` (AD-3): `text_in_numeric`, `invalid_date`, `broken_encoding`,
   `oversized_string`, `illegal_null`. A fault is toggled by including/excluding its
   mutator from the chain (`ChaosConfig.mutators`), so any subset can run.
2. **Each enabled fault appears in the output** — for the columns it targets, each
   mutator replaces a configurable proportion of cells with its violation (a
   non-numeric token in a numeric column; an unparsable/out-of-range date string in a
   datetime column; a broken-encoding/mojibake/control-char string; an oversized
   string; a null in a non-nullable column) and every injected cell is recorded in the
   `FaultManifest`.
3. **Targeting by column and type** — with no `columns`, each mutator targets the
   columns of the types it applies to (numeric for text-in-numeric, datetime for
   invalid-date, text for encoding/oversized, non-nullable for illegal-null); an
   explicit `columns` list targets exactly those; a column of the wrong type raises a
   typed `ChaosError`. Non-target columns are untouched.
4. **Deterministic (AD-4/AD-11)** — cell selection and the fault token draw from the
   injected `rng`; same seed + params → identical output + manifest. The canonical
   Schema (logical types) is preserved; the frame dtype legitimately degrades to
   `object` where illegal values were injected (that *is* the fault).
5. **Parameterized (AD-3/AD-5)** — each mutator has a Pydantic params model
   (`columns`, `proportion`; `oversized_string` adds `size`); no-arg construction gives
   defaults (entry-point discovery), explicit params drive the library / Chaos Policy;
   all run through the Story 3.1 engine with zero engine change.

## Tasks / Subtasks

- [ ] **Task 1: Shared base** (`src/tymi/chaos/mutators/_base.py`) —
  `CellFaultParams`, a `CellFaultMutator` base (resolve targets, pick
  `round(proportion·non_null)` cells, cast the column to `object`, inject, record the
  manifest) + a shared `resolve_targets` (dedupe, frame/schema/type checks →
  `ChaosError`).
- [ ] **Task 2: The five mutators** (`src/tymi/chaos/mutators/format_type.py`) — each a
  thin subclass supplying its applicable types, `fault_type`, and fault-value
  generator; `IllegalNullMutator` defaults to non-nullable columns and injects nulls;
  `OversizedStringMutator` adds a `size` param.
- [ ] **Task 3: Register** (`pyproject.toml`) — all five under `tymi.mutators`;
  re-sync so `load_mutators()` discovers them.
- [ ] **Task 4: Unit tests** — each fault appears in the output + manifest; targeting
  (default by type, explicit, wrong-type → `ChaosError`, non-targets intact); nulls
  not overwritten (except illegal-null which creates them); determinism; independent
  toggling via a mixed chain through `apply_chaos`; entry-point registration.
- [ ] **Task 5: Full 3-layer `bmad-code-review` gate** before marking done.

## Dev Notes

- **Toggle = chain membership.** The Story 3.1 engine runs the mutators named in
  `ChaosConfig.mutators`, in order. So "independently toggle each fault" is exactly
  "add/remove its mutator from the chain" — no per-fault flags needed, and the faults
  compose (a chain can enable any subset). This is why each fault is its own AD-3
  plugin, not a flag on one mutator.
- **Type violations produce `object` columns — by design.** Putting text in a numeric
  column, or an unparsable date string in a datetime column, means that column can no
  longer hold its declared dtype; the base casts the target column to `object` before
  injecting. The **canonical Schema** (logical type) is preserved (AD-10) — the point
  of the fault is precisely that the *data* no longer matches the *declared* type, so
  a downstream validator/parser can catch it.
- **Non-null cells only (except illegal-null).** A format fault replaces an observed
  value, so it selects non-null cells (mirrors Story 3.2). `illegal_null` inverts this:
  it selects non-null cells in **non-nullable** columns and sets them to null — the
  "illegal" being a null where the schema forbids one.
- **Bounded manifest values.** Injected values are recorded as a bounded `repr` so an
  oversized 10k-char string or a control-char blob doesn't bloat/garble the manifest;
  the row+column locate the fault for the Story 3.6 audit.
- **Scope.** Format/type violations only. Schema/constraint breakage (missing/extra
  columns, duplicate PK, orphan FK) is Story 3.4; the declarative Chaos Policy +
  `tymi chaos` CLI is Story 3.5; the bidirectional manifest audit is Story 3.6.

### References

- [Source: epics.md#Epic-3 Story 3.3; FR-13, FR-14]
- [Source: ARCHITECTURE-SPINE.md — AD-3 (entry points), AD-4/AD-11 (RNG), AD-5 (plugin
  params), AD-10 (canonical Schema)]
- [Source: 3-2-out-of-distribution-mutators.md — the Pydantic parameter pattern +
  non-null targeting reused here]

## Dev Agent Record

### Agent Model Used

Claude Opus 4.8 (claude-opus-4-8)

### Debug Log References

- All deps/tests run **inside the devcontainer** (`devcontainer exec`): `uv sync`
  (registers the five entry points), `uv run ruff check .` / `uv run lint-imports` →
  clean (2 contracts kept); `uv run pytest tests/unit` → 349 passed.
- `load_mutators()` → the six mutators (`outlier` + the five format/type faults).

### Completion Notes List

- Five format/type fault plugins on a shared `CellFaultMutator` base, registered under
  `tymi.mutators` and toggled by chain membership; each records a bounded manifest
  entry and preserves the canonical Schema while the frame dtype degrades to `object`.
- **Full 3-layer `bmad-code-review` gate** (Blind + Edge Case + Acceptance). No HIGH
  correctness defect in the injection/manifest logic (manifest↔frame consistency,
  determinism, non-null targeting, object-cast safety all verified). Fixed 1
  HIGH-impact realism/robustness issue: `broken_encoding` used a **lone surrogate**
  (`"caf\udce9"`, invalid UTF-8) that made the whole chaos Dataset un-exportable —
  CSV/JSON/Parquet all raised `UnicodeEncodeError` at export, far from the cause →
  replaced with corrupt-but-serializable tokens (control bytes, mojibake, replacement
  char) so chaos output can still be fed downstream. Fixed 2 MEDIUM: a positive
  `proportion` on a small column silently no-op'd via banker's rounding
  (`round(0.05·10)=0`) → shared `cell_count` guarantees ≥1 corrupted cell (also
  applied to `OutlierMutator`); `oversized_string`'s `size` was unbounded → capped at
  10 MB. Closed test gaps: broken-encoding export survives, small-column non-no-op,
  manifest-value boundedness (≤80), strict manifest count, and added a valid-syntax
  **out-of-range** date token (`10000-01-01`) so "invalid AND out-of-range" is
  covered. Noted for Story 3.6: in a multi-mutator chain a later fault may overwrite a
  cell an earlier one recorded, so the audit must reconcile per-mutator snapshots
  against the final frame (an inherent Story 3.1 chain semantic). +5 tests → 349 unit.
  All ACs satisfied.

### File List

- `src/tymi/chaos/mutators/_base.py` (new — `CellFaultMutator`, `CellFaultParams`,
  `cell_count`, `choose_tokens`)
- `src/tymi/chaos/mutators/format_type.py` (new — the five mutators)
- `src/tymi/chaos/mutators/outlier.py` (modified — reuse `cell_count`, Story 3.2)
- `pyproject.toml` (modified — five entry points under `tymi.mutators`)
- `tests/unit/test_format_type_mutators.py` (new)
- `tests/unit/test_plugins.py` (modified — expects all registered mutators)
- `docs/status.md` (modified)

## Change Log

| Date | Change |
| --- | --- |
| 2026-07-04 | Implemented Story 3.3 — five format/type violation mutators (`text_in_numeric`, `invalid_date`, `broken_encoding`, `oversized_string`, `illegal_null`) on a shared `CellFaultMutator` base; registered under `tymi.mutators`, toggled by chain membership, run via the Story 3.1 engine. |
| 2026-07-04 | Full 3-layer `bmad-code-review` gate. Replaced the un-exportable lone-surrogate `broken_encoding` token with corrupt-but-serializable ones; guaranteed ≥1 corrupted cell on small columns (shared `cell_count`, also applied to `OutlierMutator`); capped `oversized_string.size` at 10 MB; added an out-of-range date token. Closed export-survival / non-no-op / manifest-bound / count test gaps. 349 unit. All ACs satisfied. Status → done. |
