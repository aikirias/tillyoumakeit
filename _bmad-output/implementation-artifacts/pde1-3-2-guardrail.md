---
baseline_commit: 08e3d39
---

# Story 3.2 (PRD 1, Epic 3): Non-production destination guardrail

Status: done

## Story

As a self-service provisioner, I want provisioning to refuse a production destination and always
obfuscate, so that I cannot accidentally write to prod or ship un-obfuscated data (PDE-14, closes
OQ-2; AD-18).

## Acceptance Criteria

1. Given a Spec destination block, when I provision, the destination must carry an explicit
   `environment: nonprod` affirmation and not match the configured prod deny-list; a missing
   affirmation or a deny-list match aborts before any write (AD-18, fail-closed default).
2. There is no code path that loads a non-`GatedDataset` into a destination (AD-21). _(Deferred
   to Story 3.3: the provisioning load step is wired there and calls `require_gated` before
   `EngineAdapter.load`. This story delivers the guardrail that runs immediately before that load;
   the AD-21 type gate is enforced at the load call site in 3.3.)_
3. OQ-2's detection mechanism (affirmation + deny-list format) is fixed and documented.

## Tasks

- [ ] `DestinationSpec` (`environment`, `host`, `database`) on `Spec` (`destination` optional).
- [ ] `tymi/provision/guardrail.py` — `assert_nonprod_destination(destination, *, deny_list)`:
  fail-closed unless `environment == "nonprod"` and neither host nor database matches a prod
  deny-list glob. `NONPROD`, `DEFAULT_PROD_DENY_LIST`.
- [ ] `GuardrailError(TymiError)`.
- [ ] Exclude `destination` from the consistency fingerprint (operational, not data identity).
- [ ] import-linter: `tymi.provision` added to the forbidden set for core/ports/domain.
- [ ] Unit tests: accept nonprod non-denied; reject missing destination / non-nonprod / deny-list
  match; empty deny-list still requires the affirmation; fingerprint ignores destination.
- [ ] Full 3-layer `bmad-code-review` gate.

## Dev Notes

- **OQ-2 resolution (documented in `guardrail.py`):** the destination is affirmed non-prod by an
  explicit `environment: nonprod` in the Spec's `destination` block; production is detected by a
  **configured prod deny-list** of case-insensitive host/database glob patterns
  (`DEFAULT_PROD_DENY_LIST = ("*prod*", "*production*")`, overridable). **Fail-closed default:** a
  missing destination or a non-`nonprod` affirmation aborts; an empty deny-list still requires the
  affirmation — it never means "allow all".
- **AC2** is the AD-21 type gate: `require_gated` (Story 1.1) already makes a non-`GatedDataset` a
  type error at the load boundary; the guardrail runs *before* `EngineAdapter.load`. The actual
  load wiring is Story 3.3.
- **Fingerprint:** the destination is where you provision, not what the data *is*, so it is
  excluded from the AD-15 consistency-unit fingerprint.

## Dev Agent Record

### Debug Log References

- `uv run pytest tests/unit/test_guardrail.py -q` → 12 passed.
- `uv run pytest -q` → 625 passed; `uv run ruff check` + `uv run lint-imports` clean (2 contracts kept).

### Completion Notes List

- New `provision/guardrail.py` `assert_nonprod_destination` fails closed unless the destination
  affirms `environment: "nonprod"` (exact, case-sensitive) and neither host nor database matches a
  case-insensitive prod deny-list glob. New `DestinationSpec` on `Spec` (excluded from the
  consistency fingerprint); `GuardrailError`; `tymi.provision` added to the import-linter forbidden
  set (core/ports/domain never import it). **OQ-2 resolved + documented** in `guardrail.py`.
- Ran the full 3-layer gate. **Blind found no bypass** (fnmatch treats the target as literal and
  the pattern as glob; case-folding symmetric; both host and database checked; affirmation
  fails-closed on any case/whitespace variant). Findings applied:
  - **AC2 honesty (Acceptance) — over-claimed.** "No code path loads a non-`GatedDataset`" is the
    AD-21 type gate wired at the load call site in **Story 3.3**; `require_gated` is not on any load
    path yet, and the MVP export path still loads a raw `Dataset`. **Fix:** AC2 reworded as
    explicitly deferred to 3.3 (this story ships the guardrail that runs immediately before that
    load).
  - **E4 (docs) — bare deny-list tokens are exact-match** (a naive `("prod",)` misses `prod-db-01`);
    documented that entries are globs (use `*prod*`).
  - Added tests: affirmation is case-sensitive/whitespace-strict (fail-safe); an affirmed nonprod
    target with no host/database passes (affirmation is the primary gate).
- **Accepted (by design, AD-18):** an author who can edit the Spec can affirm `nonprod` and point at
  a prod host the deny-list doesn't name — the affirmation is the human declaration, the deny-list
  is belt-and-braces. Over-blocking on a `*prod*` substring (e.g. `reproduce-db`) is the fail-safe
  direction.

### File List

- `src/tymi/provision/__init__.py`, `src/tymi/provision/guardrail.py` (new) — the guardrail.
- `src/tymi/config/spec.py` (modified) — `DestinationSpec` + `Spec.destination`.
- `src/tymi/config/consistency.py` (modified) — destination excluded from the fingerprint.
- `src/tymi/core/errors.py` (modified) — `GuardrailError`.
- `pyproject.toml` (modified) — `tymi.provision` forbidden for core/ports/domain.
- `tests/unit/test_guardrail.py` (new) — 12 tests.

## Change Log

| Date | Change |
| --- | --- |
| 2026-07-05 | Drafted Story 3.2 — non-prod destination guardrail (AD-18, OQ-2). |
| 2026-07-05 | Implemented; passed the 3-layer gate (no bypass; AC2 deferred to 3.3 honestly). Status → done. |
