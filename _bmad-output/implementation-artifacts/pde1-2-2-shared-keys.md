---
baseline_commit: 96bdc1a
---

# Story 2.2 (PRD 1, Epic 2): Position-derived shared keys and reserved fixture keyspace

Status: done

## Story

As a self-service provisioner, I want declared shared keys generated identically across teams and
clear of fixture keys, so that datasets from different teams join consistently (PDE-12, closes
OQ-5).

## Acceptance Criteria

1. Given a Spec declaring `shared` key columns and a reserved fixture keyspace block, when I
   generate, then shared keys are emitted by `key(table, row_position)` — independent of source
   and seed — so two teams with the same pinned row counts get identical keys (AD-16, PDE-12).
2. Generated keys never enter the reserved fixture block; disjointness is validated and a clash
   fails closed (PDE-10).
3. OQ-5's reserved-keyspace convention is fixed and documented.

## Tasks

- [ ] `reserved_key_block: int` on `TableSpec` (the low block `[0, R)` reserved for fixtures).
- [ ] `tymi/synth/keys.py` — `position_keys(reserved, n)`, `apply_shared_keys(...)` (rewrite
  declared shared columns to `reserved + position`, remap referencing FKs, validate keyspace),
  `shared_specs(spec)`.
- [ ] `KeyspaceError(GenerationError)` — fail-closed for keyspace violations.
- [ ] Wire shared-key emission into `generate_from_spec` (substreams → shared keys → seal).
- [ ] Unit tests: keyer; source+seed-independent cross-team identity; FK remap keeps RI;
  fail-closed (fixture outside block, shared-FK, unknown table/column).
- [ ] Full 3-layer `bmad-code-review` gate.

## Dev Notes

- **OQ-5 resolution (documented in `keys.py`):** the reserved fixture block is the contiguous
  integer range `[0, reserved_key_block)` per table; fixtures live inside it, generated shared
  keys at/above it (`[R, R+n)`) — disjoint by construction, validated fail-closed.
- **Position-derived, not seed-derived:** `key(table, pos) = R + pos`. Depends only on the table
  (which column) and row position — so two teams match given identical pinned row counts,
  regardless of source values or seed. (Supersedes PDE-12's earlier "seed-derived" wording.)
- **FK remap:** a shared PK is rewritten, so every FK that references it is remapped by the same
  `old → new` mapping (RI across the whole DB). A shared column may not itself be an FK
  (fail-closed) — it must follow its parent's key, not be rewritten independently.
- Fixtures overlay is Story 3.1; here the reserved block only *partitions* the keyspace for them.

## Dev Agent Record

### Debug Log References

- `uv run pytest tests/unit/test_keys.py tests/unit/test_whole_db.py -q` → 21 passed.
- `uv run pytest -q` → 589 passed; `uv run ruff check` + `uv run lint-imports` clean (2 contracts kept).

### Completion Notes List

- New `synth/keys.py`: `apply_shared_keys` rewrites declared shared columns to position-derived
  keys `reserved + col_offset + pos` and remaps every referencing FK (RI across the whole DB);
  `KeyspaceError(GenerationError)` fails closed on violations; `TableSpec.reserved_key_block`
  reserves `[0, R)` for fixtures. Wired into `generate_from_spec` (substreams → shared keys →
  seal). **OQ-5 resolved + documented** in the `keys.py` docstring.
- Ran the full 3-layer gate. AC1/AC2/AC3 met; findings applied:
  - **HIGH (Edge) — two shared columns in one table got identical values** (`new_keys` didn't
    depend on the column). **Fix:** each shared column is packed into a disjoint sub-range via a
    per-column `offset` (all a table's shared columns share the pinned row count `n`), so they stay
    distinct *and* cross-team-stable. Test.
  - **MED (both) — a non-unique shared column collapsed the old→new map**, silently mismapping
    referencing FKs. **Fix:** a shared key must be unique → fail closed. Test.
  - **MED (Blind) — sharing part of a composite PK/FK broke RI silently.** **Fix:**
    `_composite_referred_columns` → sharing a column that participates in a composite FK reference
    fails closed (Phase 1 scope). Test.
  - **LOW (Blind) — the seal gate could regenerate a shared column that is sensitive but not a
    PK/FK**, destroying the cross-team key. **Fix:** `_seal_guard` now also excludes shared
    columns (synthetic position-derived values, not real data). E2E test proves a shared+sensitive
    key is not regenerated.
  - **Coverage (Acceptance) — FK-remap RI untested end-to-end.** **Fix:** added
    `test_shared_pk_remaps_child_fks_end_to_end` through `generate_from_spec`.
  - Preserved the column's declared dtype on rewrite (nullable `Int64`) instead of raw numpy int64.
- **Accepted / deferred:** `fixture_keys_by_table` validation + the reserved-block partition exist
  but fixtures are not overlaid yet (Story 3.1 wires them; the disjointness validator is exercised
  via the primitive). Non-int fixture keys would raise `TypeError` not `KeyspaceError` — reachable
  only once fixtures are wired; Story 3.1 owns the full fixture-input validation.

### File List

- `src/tymi/synth/keys.py` (new) — `position_keys`, `apply_shared_keys`, `shared_specs`,
  `_composite_referred_columns`, `_validate_fixture_block`.
- `src/tymi/core/errors.py` (modified) — `KeyspaceError(GenerationError)`.
- `src/tymi/config/spec.py` (modified) — `TableSpec.reserved_key_block`.
- `src/tymi/synth/whole_db.py` (modified) — shared-key emission wired in; `_seal_guard` excludes
  shared columns.
- `tests/unit/test_keys.py` (new) — 14 tests.

## Change Log

| Date | Change |
| --- | --- |
| 2026-07-05 | Drafted Story 2.2 — position-derived shared keys + reserved keyspace (AD-16, OQ-5). |
| 2026-07-05 | Implemented; passed the 3-layer gate (per-column ranges, unique/composite fail-closed, seal excludes shared cols). Status → done. |
