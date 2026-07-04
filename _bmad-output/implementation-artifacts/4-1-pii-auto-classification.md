---
baseline_commit: cf6a81d
---

# Story 4.1: PII / Sensitive-Column auto-classification

Status: done

## Story

As a user,
I want sensitive columns detected automatically,
so that I don't have to hand-mark every PII column.

## Acceptance Criteria

1. **Auto-detection at profile time** — with classification enabled, profiling detects
   Sensitive Columns from the sampled data (value patterns + column-name hints) and
   tags them in the Profile (they enter the `LeakageGuard`, so no raw value is stored —
   AD-6). Detects the common structured-PII types (email, phone, SSN, credit card, IP,
   IBAN) plus name/address/DOB-style columns by name.
2. **Configurable recall** — a `min_match_rate` controls how many of a column's values
   must match a PII pattern to flag it, so recall is tunable; a name-hinted column is
   flagged regardless of value match.
3. **Config override (mark / unmark)** — the final sensitive set is
   `(auto-detected ∪ source.sensitive_columns) − source.not_sensitive_columns`, so the
   user can add a column the classifier missed or unmark a false positive.
4. **Leakage gate applies to auto-classified columns (Story 2.5)** — auto-detected
   columns are hashed into the `LeakageGuard` and value-suppressed exactly like
   hand-marked ones, so the Story 2.5 gate protects them with zero extra wiring.
5. **CLI** — `tymi profile --classify-pii` enables detection; the detected columns are
   visible in the saved Profile.
6. **Deterministic + in-house (AD-9)** — the classifier is rules-based (regex on
   sampled values + name heuristics), scipy/stdlib only. Full NER (Presidio → spaCy +
   a downloaded language model) is a heavier optional backend, deferred: it pulls a
   large model download that a reproducible CI/devcontainer build should not require.

## Tasks / Subtasks

- [ ] **Task 1: Classifier** (`src/tymi/privacy/classifier.py`) —
  `classify_sensitive_columns(dataset, *, min_match_rate) -> dict[str, str]`
  (column → detected PII kind) via value regexes + column-name hints.
- [ ] **Task 2: Wire into profiling** (`src/tymi/profiling/profiler.py`,
  `src/tymi/config/models.py`) — `profile_dataset(..., classify_pii=False)` unions the
  detected columns with `sensitive_columns`, minus `not_sensitive_columns`, into the
  guard + suppression; `SourceConfig.not_sensitive_columns`.
- [ ] **Task 3: CLI** (`src/tymi/cli/app.py`) — `tymi profile --classify-pii`.
- [ ] **Task 4: Unit tests** — detects each PII kind (value + name), recall knob,
  config mark/unmark override, auto-detected column ends up in the guard + suppressed
  + gated end-to-end; deterministic; no raw values in the Profile.
- [ ] **Task 5: Full 3-layer `bmad-code-review` gate** before marking done.

## Dev Notes

- **Detection runs on the sample, tags live in the Profile (AD-6).** The classifier
  needs values, so it runs during `profile_dataset` (which holds the sampled Dataset);
  only the resulting sensitive *tags* (hashed into the `LeakageGuard`) persist — never
  the raw values.
- **Reuses Story 2.5 end-to-end.** Auto-detected columns are merged into the same
  `sensitive_columns` path that builds the guard and suppresses value-bearing stats, so
  the leakage gate, the null-generation of non-STRING sensitive columns, and the
  no-raw-value guarantee all apply unchanged.
- **Rules, not NER — a scope decision for weight, NOT a license exclusion (honest).**
  Presidio is MIT (AD-9-fine); it is deferred purely because it pulls spaCy + a large
  downloaded language model that a reproducible CI/devcontainer build should not
  require — this is weaker than the SDMetrics→copulas BUSL exclusion (which was
  AD-9-mandated) and is a **deliberate scope-down, not an architecture rule**. The
  spine's Stack was reconciled in place (Presidio struck → deferred). **Known
  limitation:** rules catch structured PII by value and name/address/DOB by *column
  name*; **free-text PII** (a `bio`/`notes` column containing "John Smith, Paris") is
  NOT detected — that is exactly what NER is for, and it is a required follow-up if
  free-text person/location recall matters. Recorded here for PO acceptance.
- **"Recall threshold" is a per-column value-match rate.** `min_match_rate` (validated
  to `(0, 1]`) is how many of a column's values must match a PII validator, not recall
  over the true-PII column set — a defensible, tunable knob, but a remapping of the
  epic's wording worth noting.

### References

- [Source: epics.md#Epic-4 Story 4.1; FR-23; SM-8]
- [Source: ARCHITECTURE-SPINE.md — AD-6, AD-9, AD-5; ports.PIIClassifier]
- [Source: 2-5-leakage-gate-sensitive-columns.md — sensitive_columns → LeakageGuard]

## Dev Agent Record

### Agent Model Used

Claude Opus 4.8 (claude-opus-4-8)

### Debug Log References

- All tests run **inside the devcontainer**: `uv run ruff check .` / `uv run
  lint-imports` → clean; `uv run pytest tests/unit` → 436 passed. No new dependency.

### Completion Notes List

- Rules-based `classify_sensitive_columns` (value validators + name hints), wired into
  `profile_dataset(classify_pii=…, not_sensitive_columns=…)` + `tymi profile
  --classify-pii`, feeding the Story 2.5 `LeakageGuard`/suppression. NER (Presidio)
  deferred; the spine's Stack was reconciled in place.
- **Full 3-layer `bmad-code-review` gate** (Blind + Edge Case + Acceptance). Fixed 2
  HIGH: a column-name hint fired regardless of type, so a numeric/boolean column
  (`product_name_id`, `credit_score`, `email_verified`, `birth_year`) was suppressed
  and generated **all-null** — name hints are now restricted to text/datetime columns
  (numeric PII is an accepted recall gap, mark it explicitly); and
  `not_sensitive_columns` overrode an **explicit** `sensitive_columns` mark (a leak) —
  an explicit mark now always wins. Fixed 3 MEDIUM/robustness: greedy value regexes
  flagged numeric-id text columns (`phone` now requires a separator/`+`, `credit_card`
  is Luhn-checked, `ip` validates octets); `min_match_rate` is validated to `(0, 1]`
  and requires a positive match rate (0.0 no longer flags everything as email); the
  classifier skips a schema-only column (was a `KeyError` in `build_leakage_guard`).
  Fixed a Luhn bug in my own patch (wrong doubling parity rejected valid cards).
  Reconciled the architecture spine (Presidio struck → deferred) and documented the
  scope-down + free-text-NER limitation honestly for PO acceptance. +8 tests → 436
  unit. All ACs satisfied (rules-only; NER deferred with PO note).

### File List

- `src/tymi/privacy/classifier.py` (new — `classify_sensitive_columns`)
- `src/tymi/profiling/profiler.py` (modified — classify_pii + override wiring)
- `src/tymi/config/models.py` (modified — `SourceConfig.not_sensitive_columns`)
- `src/tymi/cli/app.py` (modified — `tymi profile --classify-pii`)
- `tests/unit/test_pii_classifier.py` (new)
- `_bmad-output/planning-artifacts/architecture/.../ARCHITECTURE-SPINE.md` (modified —
  Presidio deferred)
- `docs/status.md` (modified)

## Change Log

| Date | Change |
| --- | --- |
| 2026-07-04 | Implemented Story 4.1 — in-house rules-based PII auto-classification (value validators + name hints) wired into the Story 2.5 leakage machinery (`classify_pii`, `not_sensitive_columns`, `tymi profile --classify-pii`). Presidio/NER deferred (weight/reproducibility); spine reconciled. |
| 2026-07-04 | Full 3-layer `bmad-code-review` gate. Fixed 2 HIGH (name hints suppressing numeric columns → null; `not_sensitive_columns` overriding an explicit sensitive mark → leak) and 3 MEDIUM (greedy phone/cc/ip regexes → in-house Luhn + octet + separator checks; `min_match_rate` validation; schema-only-column crash). Reconciled the Presidio deviation in the spine + documented the free-text-NER limitation for PO acceptance. 436 unit. Status → done. |
