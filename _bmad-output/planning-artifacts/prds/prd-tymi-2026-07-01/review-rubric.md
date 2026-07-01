# PRD Quality Review — Fake It Till You Make It (TYMI)

## Overall verdict

**PASS-WITH-FIXES.** This is a substantive, thesis-driven PRD: the dual-capability bet (Faithful Generator + Data Chaos Monkey at equal weight) is stated plainly, the FRs mostly carry testable consequences, and the Glossary/NFR/handoff scaffolding is real work, not furniture. What holds it back from a clean PASS is a broken FR-ID sequence (FR-22 is physically filed inside §4.3 out of numeric order, which makes the UJ range references incoherent), several FRs with no validating Success Metric (all of connectivity, profiling, and most chaos-injection FRs), and a real contradiction between the "zero leakage / hard requirement" framing and the sampling-based way it is actually verified. None of these are fatal, but the ID drift and the unvalidated FRs would bite Epics and QA, so they should be fixed before handoff. (Per the review note, the deferred similarity-test choice and default Tolerance are treated as intentional, not gaps.)

## Decision-readiness — adequate

Trade-offs are surfaced honestly: Non-Goals (§5), Out-of-Scope (§6.2), and the `[NOTE FOR PM]` on formal differential privacy (§6.2) name what was given up. Open Questions (§8) are genuinely open, and the "Resolved" list shows decisions were actually taken (engines equal-priority, no-auth, YAML). The one weakness is that the biggest product tension — "0 real values / hard requirement" (NFR-1, SM-2) vs. the fact that it is *verified by sampling* (FR-9, SM-2) — is never called out as a tension. A decision-maker reading SM-2 could believe leakage is provably zero when the acceptance mechanism is probabilistic.

### Findings
- **high** Zero-leakage is asserted as a hard guarantee but verified only by sampling (§10 NFR-1, §7 SM-2, §4.3 FR-9) — NFR-1 says "hard requirement, not aspirational" and SM-2 says "0 real sensitive source values appear," yet FR-9's consequence and SM-2's method are "verifiable by sampling" / "automated sampling in CI," which cannot prove absence. This is an unacknowledged tension a reviewer would immediately push on. *Fix:* either reframe SM-2 as "no leakage detected by the defined sampling protocol at rate R" and add a `[NOTE FOR PM]` acknowledging it is a detection guarantee not a proof, or specify a deterministic exact-match check over the full output (not a sample) so the "0 / hard" language is actually earned.

## Substance over theater — strong

No persona theater (three named protagonists, each drives a UJ and an FR cluster). The differentiation is concrete (statistical fidelity + auditable chaos in one tool, Gretel-inspired but CPU-light). NFRs mostly carry product-specific thresholds (≥10M rows, byte-identical, configurable memory limit) rather than boilerplate. The Vision (§1) is category-specific and would not swap cleanly into another PRD.

### Findings
- **low** NFR-7 (Observability) and the §11 "portability NFR" are the thinnest items (§10, §11) — "structured logs + run artifacts" and "must run on a developer's machine" are near-boilerplate with no bound. *Fix:* optionally tie NFR-7 to a concrete artifact contract (e.g. "every run emits Fidelity Report + Fault Manifest with a run-id resolvable in logs") — much of this is implied by FR-15/FR-17 already.

## Strategic coherence — strong

The PRD has a clear thesis (statistically-real synthetic data *and* auditable controlled chaos, replacing prod data in non-prod while stress-testing pipelines) and the features serve it. Success Metrics validate the thesis (fidelity, leakage, chaos-manifest contract) rather than vanity activity metrics, and two counter-metrics (SM-C1 memorization, SM-C2 trivial chaos) are present and correctly point at the real failure modes. MVP scope kind (problem-solving + platform) matches the scope logic.

### Findings
- **medium** SM-5 (Flow adoption) is not cross-referenced to any FR, breaking the PRD's own stated convention (§7) — the header says "Each SM cross-references the FR(s) it validates," but SM-5 has no "Validates FR-x". It implicitly covers FR-19/FR-21. *Fix:* add "Validates FR-18, FR-19, FR-21" (the end-to-end flow) to SM-5, or state explicitly that it is a qualitative cross-cutting metric with no single FR.

## Done-ness clarity — adequate

Most FRs carry at least one testable consequence, and several are genuinely strong (FR-1 credential handling, FR-9 no-orphan-FK, FR-15 bidirectional manifest contract, FR-22 100%-of-conditioned-rows). But a cluster of consequences lean on undefined magnitudes, and a couple are existence-only (present/absent) rather than measuring fidelity.

### Findings
- **medium** "within a margin" is used as an acceptance bound without defining or deferring the margin (§4.4 FR-11, FR-14) — "matches the configured one within a margin" is untestable as written; unlike Tolerance (explicitly deferred to Architecture in OQ-1), this "margin" is neither defined nor flagged as deferred. *Fix:* name it (e.g. "within ±X percentage points, X per Architecture") and add it to §8 Open Questions if the value is deferred, so it is not silently ambiguous.
- **medium** FR-5's only consequence is existence, not fidelity (§4.2 FR-5) — "The Profile includes a representation of the detected correlations" is satisfied by an empty/degenerate representation; it does not test that correlations are *correctly* detected. FR-8 (correlation *preservation*) is the tested one, but detection itself is unverified. *Fix:* add a consequence like "on a reference dataset with a known correlation ≥ r, the detected representation recovers it within Tolerance."
- **low** FR-23 references a "configurable recall threshold" with no default and no validating SM (§4.6 FR-23) — recall is the whole point of PII classification (a miss is a leak vector) yet no SM binds it and the threshold is unset. *Fix:* set a default recall floor for reference datasets, and consider adding it to SM-6 or a new SM; at minimum add to §8.
- **low** FR-17's consequence is existence-only (§4.5 FR-17) — "reports a per-column similarity metric and a global correlation metric" verifies the report contains the fields, not that they are correct; the correctness is carried by SM-1. Acceptable given SM-1, noted for completeness.

## Scope honesty — strong

Omissions are explicit and load-bearing: §2.2 Non-Users, §5 Non-Goals, §6.2 Out-of-Scope all do real work, and the `[NOTE FOR PM]` on differential privacy flags an unresolved product tension honestly. Assumptions are tagged inline and indexed (§9), and the "Resolved / Confirmed" lists show de-scoping and decisions were done in the open, not silently. Open-items density is appropriate for a green-light-to-build PRD (4 open questions, all narrow/technical).

### Findings
- **low** Two `[ASSUMPTION]` tags in §5 and the §11/§12 tags are indexed inconsistently (§9) — see Mechanical notes; roundtrip is *mostly* clean but a few inline tags (§11 read-only connections, §12 SemVer, §12 Python 3.11 floor) are not in the §9 index. *Fix:* add the missing three to §9 or state that §9 indexes only product-scope assumptions.

## Downstream usability — thin

This is a chain-top PRD (feeds UX → Architecture → Epics, per §13), so traceability matters most here — and this is where the PRD is weakest. The FR-ID sequence is broken, the UJ→FR range references do not resolve cleanly, and a set of foundational FRs have no Success Metric to close the loop. Each of these will cost the downstream workflows.

### Findings
- **critical** FR-IDs are non-contiguous and out of physical order; FR-22 is filed inside §4.3 between FR-9 and FR-10 (§4.3) — numeric order is FR-1..9, **22**, 10..21, 23..25. FR-22 (Conditional Generation) sits physically in §4.3 ahead of FR-10. Epics/story tooling that assumes contiguous, in-order IDs will mis-slice. *Fix:* renumber so IDs are contiguous and in document order (e.g. make Conditional Generation FR-10 or move it after FR-21 and renumber), or add an explicit note that FR numbering is stable-but-non-sequential by design and that FR-22 belongs to §4.3.
- **high** UJ→FR range references do not resolve (§2.3 UJ-3, UJ-1) — UJ-3 says "Realizes UJ via **FR-17..FR-22**," but that inclusive range pulls in FR-22 (Conditional Generation), which is tagged "Realizes UJ-1," not UJ-3, and physically lives in §4.3, outside §4.5. UJ-1 says "FR-1..FR-9" which is clean. The FR-17..FR-22 range is therefore both a dangling reference (spans a gap in numbering) and a contradiction (FR-22 claims UJ-1). *Fix:* replace range shorthand with explicit lists per UJ (UJ-3 → FR-6, FR-15, FR-16, FR-17, FR-18, FR-19, FR-20, FR-25 per the "Realizes UJ-3" tags actually on the FRs), and reconcile with the per-FR "Realizes" tags so both directions agree.
- **high** Several FRs have no validating Success Metric (§4, §7) — no SM references FR-1, FR-2, FR-3, FR-4, FR-5, FR-6, FR-10, FR-11, FR-12, FR-13, FR-14, FR-17, FR-18, FR-19, FR-20, FR-21, FR-22, FR-23. The chaos-injection FRs (FR-11/12/13/14) are especially notable: only the manifest (FR-15) is validated by SM-3, so the *injection* families have no outcome metric. *Fix:* add SMs (or explicitly note which FRs are capability-only and intentionally metric-free). At minimum bind the three chaos fault-families and PII recall (FR-23) to measurable SMs, since those are core-thesis behaviors.
- **medium** Per-FR "Realizes" tags and per-UJ "Realizes UJ via" ranges are maintained separately and disagree (§2.3, §4) — e.g. FR-16 is tagged "Realizes UJ-1, UJ-2" but falls inside UJ-3's FR-17..22 range framing and UJ-2's FR-10..16 range. The two traceability directions are not reconciled. *Fix:* pick one direction as source of truth (recommend per-FR tags) and derive UJ realizations from it.

## Shape fit — strong

Correctly shaped as a consumer/developer-tool PRD with load-bearing UJs (three named protagonists — Dana, Marco, Sofía — each carrying context inline and driving a feature cluster). Not over-formalized (no UJ bloat for the single-operator paths) and not under-formalized (UX/perf/security given bounds). The Developer-Product Surface (§12) and Downstream Handoffs (§13) sections are appropriate for a chain-top technical tool. No shape mismatch.

### Findings
- (none)

## Mechanical notes

- **Glossary drift (medium).** UJ prose lowercases defined terms: "**fidelity report**" (UJ-1) vs Glossary **Fidelity Report**; "**fault manifest**" (UJ-2) vs **Fault Manifest**; "profile" / "chaos policy" (UJ-2) vs **Profile** / **Chaos Policy**. *Fix:* capitalize the Glossary terms in UJ prose (or accept lowercase narrative but do so consistently).
- **"similarity test" is an undefined term (intentional).** Used in SM-1, FR-7, UJ-1 but absent from the Glossary. Per OQ-1 and the review note, the *choice* of test is deferred to Architecture — treated as intentional. Minor suggestion: add a Glossary stub ("Similarity Test — per-column distribution comparison; concrete test deferred to Architecture") so downstream readers do not treat it as an orphan.
- **"Privacy Metric" singular vs "Privacy Metrics" plural (low).** Glossary defines singular; §4.6/§7 use plural. Cosmetic.
- **ID continuity (critical/high — see Downstream usability).** FR sequence: 1–9, 22, 10–21, 23–25 — non-contiguous and out of physical order. No duplicate IDs. NFR-1..7, SM-1..6 + C1/C2, UJ-1..3 are all clean and contiguous.
- **Assumptions roundtrip (low).** §9 indexes: §2.2 DP, §4.2 categoricals, §5 business rules, §5 forecasting, §7 SM-5. Inline `[ASSUMPTION]` tags NOT in the index: §11 "read-only connections recommended," §12 "3.11+ as floor," §12 SemVer/versioning. *Fix:* add these three or scope §9 to product assumptions only.
- **UJ protagonist naming — clean.** All three UJs have named protagonists (Dana, Marco, Sofía) carrying role/context inline.
- **Required sections — present.** Vision, Target User/JTBD, Glossary, Features/FRs, Non-Goals, MVP Scope, Success Metrics, Open Questions, Assumptions Index, NFRs, Constraints, Developer Surface, Handoffs all present and appropriate for the stakes.
