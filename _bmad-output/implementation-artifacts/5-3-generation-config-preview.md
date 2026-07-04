---
baseline_commit: 98680c7
---

# Story 5.3: Faithful Generation Configuration and Preview

Status: done

## Story

As a user,
I want to configure faithful generation and preview a sample,
so that I can tune it visually before exporting.

## Acceptance Criteria

1. **Configure + preview** — given a Profile in session, setting rows / seed / tolerance /
   conditions and clicking "Preview" generates a faithful synthetic sample in-process and
   renders it.
2. **Source-vs-generated comparison** — for each comparable column the page shows a
   side-by-side distribution comparison (source distribution from the Profile aggregates
   vs the generated sample's distribution).
3. **Conditions honored** — a condition (e.g. `region=LATAM`, `age in [18,25]`) restricts
   the preview so every row satisfies it (Story 2.4 semantics via `parse_conditions`).
4. **Choices written back to the shared Config** — rows/tolerance/conditions land on
   `Config.generation`, the seed on `Config.seed` — the same artifact the CLI reads
   (AD-5/AD-8), so nothing is UI-only.
5. **No profile → guidance** — with no Profile yet, the page directs the user to the
   Profile step (no crash).

## Tasks / Subtasks

- [x] **Task 1: Config field** (`src/tymi/config/models.py`) — added
  `GenerationConfig.conditions: list[str]` (raw `col=value` strings) so conditions persist
  in the shared Config.
- [x] **Task 2: Services** (`src/tymi/ui/services.py`) — `set_generation` (re-validated
  write of rows/seed/tolerance/conditions), `run_generation_preview` (parse conditions +
  `generate_faithful`), `generation_comparison` (per-column source-vs-gen frames),
  `ComparisonChart` dataclass.
- [x] **Task 3: App page** (`src/tymi/ui/app.py`) — `render_generate`: rows/seed/tolerance/
  conditions form (pre-filled from the Config), preview, sample table + comparison charts;
  write back to Config on success.
- [x] **Task 4: Tests** — preview generates a conditioned sample (equality + range 100%
  satisfy); comparison frames align source vs generated (incl. out-of-range mass, and the
  datetime/text exclusion); `set_generation` persists + re-validates + YAML round-trips;
  `AppTest` (profile → preview → sample + charts, full write-back); no-profile guidance;
  determinism.
- [x] **Task 5: Full 3-layer `bmad-code-review` gate** before marking done.

## Dev Notes

- **Same generation path as the CLI (AD-8).** `run_generation_preview` calls the identical
  `generate_faithful(profile, rows=, rng=make_rng(seed), conditions=parse_conditions(...))`
  the CLI `generate` command uses — the preview is the real output, not a UI mock, so a
  given (Profile, seed, conditions) is reproducible (AD-4/AD-11) and matches a CLI run.
- **Comparison from aggregates + the generated sample (AD-6).** The source side of each
  comparison is the Profile's stored distribution (numeric histogram over its own bins;
  categorical frequencies) — never raw source rows; the generated side is computed from
  the freshly generated sample over the same bins/categories, so the two are directly
  comparable.
- **Conditions persist in the Config.** A new `GenerationConfig.conditions` (list of raw
  `col=value` strings) lets the UI write conditions back into the one shared Config; the
  preview re-parses them with the Story 2.4 `parse_conditions`.
- **CLI↔UI parity gap (documented).** The UI writes conditions/rows/tolerance into
  `Config.generation` and round-trips them through the form, but the CLI `generate` command
  currently reads its inputs from `--rows`/`--seed`/`--where` options, **not** from
  `Config.generation` — so a Config authored in the UI is not consumed by `tymi generate`
  today. This is a pre-existing CLI design (generate loads a Profile, not a Config);
  wiring `generate` to honor `Config.generation` is a follow-up for the pipeline
  orchestrator. The *generation path itself* (generate_faithful + parse_conditions) is
  identical, so the previewed output matches an equivalent CLI run.
- **Comparison is numeric + categorical only.** datetime and text columns are excluded
  from the source-vs-generated comparison (a KS/TV-style marginal comparison needs binned
  numeric or categorical frequencies); the UI discloses this with a caption.
- **`tolerance` is a downstream setting.** It is persisted to `Config.generation` for the
  fidelity/quality report (Stories 2.7/4.3) — `generate_faithful` takes no tolerance, so
  it does not affect the preview itself (consistent with the CLI).
- **Scope.** Config + preview + comparison. Exporting the generated data and the fidelity
  report live in Story 5.5; this page only previews.

### References

- [Source: epics.md#Epic-5 Story 5.3; FR-22]
- [Source: ARCHITECTURE-SPINE.md — AD-4/AD-8/AD-10; generator.generate_faithful; conditions.parse_conditions]

## Dev Agent Record

### Agent Model Used

Claude Opus 4.8 (claude-opus-4-8)

### Debug Log References

- `uv run pytest tests/unit/test_ui_generate.py -q` → 12 passed.
- `uv run pytest -q` → 516 passed; `uv run ruff check` + `uv run lint-imports` clean.

### Completion Notes List

- Added `GenerationConfig.conditions`; `set_generation` / `run_generation_preview` /
  `generation_comparison` to `services.py`; the `render_generate` page (pre-filled from the
  Config, writing back on success). Preview uses the identical `generate_faithful` +
  `parse_conditions` path as the CLI (AD-8, AD-4).
- Ran the full 3-layer `bmad-code-review` gate (Blind + Edge + Acceptance). All ACs met.
  Findings applied:
  - **MED (Blind + Edge)** — `set_generation` used `model_copy(update=)`, which skips
    validators, so `rows=0` / `tolerance>1` persisted an invalid Config; now re-validates
    via `Config.model_validate(...)` and strips blank condition lines.
  - **MED (Edge)** — the numeric comparison renormalized in-range survivors to 1, hiding
    generated mass that fell outside the source bin range (a targeted out-of-range
    condition); the generated series is now normalized over the total generated count, so
    out-of-range mass shows as missing (bars < 1).
  - **LOW (Blind)** — a generated null became a spurious `"nan"` category; `dropna()`
    before `value_counts()`.
  - **Acceptance/Edge disclosure** — datetime/text columns are excluded from the
    comparison; the UI now says so via a caption, and a test asserts it. Added a range-
    condition preview test and strengthened the AppTest write-back assertions.
- Documented the CLI↔UI parity gap (the CLI `generate` reads `--where`, not
  `Config.generation.conditions`) and that `tolerance` is a downstream (report) setting,
  not a generation input.

### File List

- `src/tymi/config/models.py` (modified) — `GenerationConfig.conditions`.
- `src/tymi/ui/services.py` (modified) — `set_generation`, `run_generation_preview`,
  `generation_comparison`, `_normalize`, `ComparisonChart`.
- `src/tymi/ui/app.py` (modified) — `render_generate` page + wiring.
- `tests/unit/test_ui_generate.py` (new) — 12 tests.
- `tests/unit/test_ui_shell.py` (modified) — placeholder-step tests updated (Generate is
  now a real page).

## Change Log

| Date | Change |
| --- | --- |
| 2026-07-04 | Drafted Story 5.3 — faithful generation config + preview. |
| 2026-07-04 | Implemented config field + services + generate page; passed the 3-layer gate (validated write-back, honest out-of-range comparison, disclosures). Status → done. |
