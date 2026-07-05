---
baseline_commit: 69879b7
---

# Story 2.1 (PRD 1, Epic 2): Per-table RNG substreams

Status: done

## Story

As a maintainer, I want each table generated from a deterministic per-table RNG substream, so
that a table's output is independent of other tables' row counts or order (AD-20) — the
property that keeps the same shared entities' relationships stable across teams.

## Acceptance Criteria

1. Each table draws from a substream derived from `(seed, table_name)`, not a single shared
   generator (AD-20).
2. A table's output (rows and FK edges) is byte-identical regardless of another table's row
   count or the generation order.
3. Determinism per the consistency unit still holds end-to-end (same seed → byte-identical).

## Tasks

- [ ] `tymi/synth/substreams.py` — `table_substream(seed, table_name)` (SeedSequence over
  `[seed, hashlib-entropy(name)]`; process-independent, negative-seed safe).
- [ ] Replace `generate_related`'s single shared `rng` param with `seed`; derive a fresh
  substream per table inside the topological loop.
- [ ] Update the one caller (`whole_db.generate_from_spec`) and all `generate_related` test
  call sites.
- [ ] Unit tests: substream determinism / name-independence / seed-sensitivity / negative seed;
  end-to-end independence of unrelated row counts + generation order.
- [ ] Full 3-layer `bmad-code-review` gate.

## Dev Notes

- **Why hashlib, not `hash()`.** Python's built-in `hash()` is per-process salted, so it would
  give different substreams on different runs — fatal for cross-team reproducibility. `blake2b`
  is stable across processes/machines.
- **FK edges.** A child's FK-edge sampling now draws from the *child's* substream over the
  parent's finalized (position-derived) keys, so edges stay stable when unrelated tables change;
  they legitimately depend only on the child's own substream + the parent's row count.
- **Signature change is intended** (AD-20 calls it out): the shared-rng threading is the defect.

## Dev Agent Record

### Debug Log References

- `uv run pytest tests/unit/test_substreams.py tests/unit/test_relational.py tests/unit/test_whole_db.py -q` → 32 passed.
- `uv run pytest -q` → 575 passed; `uv run ruff check` + `uv run lint-imports` clean (2 contracts kept).

### Completion Notes List

- New `synth/substreams.py` `table_substream(seed, name)`; `generate_related` now takes `seed`
  and derives a fresh per-table substream inside the topological loop (shared-rng threading
  removed). Sole `src` caller (`whole_db`) + all `generate_related` test call sites migrated.
- Ran the full 3-layer gate. Findings applied:
  - **HIGH (Blind) — mis-migration.** The mechanical `rng=make_rng(N)` → `seed=N` sweep also hit
    two `adapter.sample(..., rng=make_rng(1))` calls in `test_relational_integration.py` (sample
    takes `rng`, not `seed`) → `TypeError`. Masked locally because those tests are docker-gated
    and skip without Docker. **Fix:** reverted those two calls to `rng=make_rng(1)` and restored
    the import; audited every remaining `seed=` — all are on `generate_related`.
  - **MED (Acceptance+Blind) — AD-20 FK-edge stability unproven + docstring overstated.** The
    row-invariance test used FK-less tables, so it proved the rows claim but not the FK-edge
    claim (the actual wedge). **Fix:** added `test_child_fk_edges_stable_when_unrelated_table_
    changes` (parent + FK-child + unrelated table; growing the unrelated table 25× leaves the
    child's frame byte-identical) and softened the docstring (a child legitimately tracks its own
    parent's row count; independence is w.r.t. *unrelated* tables).
  - **LOW — 64-bit masking / name-entropy collision.** Documented in the substream docstring
    (negligible: birthday bound ~2³² tables; seeds are small ints).
- **Accepted:** `seed=None` would raise a bare `TypeError` in `table_substream`, but
  `generate_related`/`Spec.seed` are typed `int` (default 0), so it is unreachable via the Spec
  path — left as the typed contract. The seal-path `make_rng(spec.seed)` in `whole_db` is a
  documented no-op (not substreamed) and outside this story's surface.

### File List

- `src/tymi/synth/substreams.py` (new) — `table_substream`, `_name_entropy`.
- `src/tymi/synth/relational.py` (modified) — `generate_related` takes `seed`, per-table substream.
- `src/tymi/synth/whole_db.py` (modified) — caller updated to `seed=spec.seed`.
- `tests/unit/test_substreams.py` (new) — 8 tests.
- `tests/unit/test_relational.py`, `tests/integration/test_relational_integration.py` (modified) —
  migrated call sites (integration `adapter.sample` correctly kept on `rng=`).

## Change Log

| Date | Change |
| --- | --- |
| 2026-07-05 | Drafted Story 2.1 — per-table RNG substreams (AD-20). |
| 2026-07-05 | Implemented; passed the 3-layer gate (fixed mis-migrated integration call, added FK-edge-stability test). Status → done. |
