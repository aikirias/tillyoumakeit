# PRD Quality Review — TYMI Deeper Chaos Monkey / Content Chaos (PRD 2)

## Overall verdict

This is a strong Fast-path first cut: a coherent, honestly-scoped capability spec with a real thesis (content chaos = the cheapest, most-differentiated wedge) and genuinely-open Open Questions rather than rhetorical ones. The strategic spine and scope discipline hold up well. The risk concentrates in done-ness: the headline falsifiable goal (G1) silently depends on reference fixtures the PRD never says exist and can't be measured until the last phase, the MCAR/MAR/MNAR "mechanism honored" claim has no stated verification method, and the CC-11 detection audit — the eval loop the whole thesis rests on — is not yet buildable because its consumer-report contract is deferred to an Open Question. All three are honestly flagged, but they mean this is a direction-setting PRD, not a green-light-to-build one — which matches its own framing.

## Decision-readiness — adequate (leaning strong)

The PRD makes decisions as decisions, not as buried "considerations." Batch/DB only (not streams), rule-based missingness before learned models, new `Mutator` plugins with zero core change, and a cheapest-first phase order are all stated flatly with what was given up (streaming, API-contract chaos, learned models → PRD 3 / deferred). Trade-offs are named, not smoothed. The four Open Questions are real unresolved tensions with no hidden answer in the next sentence — OQ-1 (who is the forcing function / concrete pull), OQ-2 (MAR/MNAR depth), OQ-3 (detection-audit contract), OQ-4 (single-table vs whole-DB) each genuinely gate a downstream decision.

The soft spot is that the load-bearing goal G1 leans on assets the PRD never accounts for. "On a reference pipeline + a reference data-QA alert suite…" — nothing in the PRD says these exist, who builds them, or whether building them is in scope. A decision-maker can't act on G1 without that.

### Findings
- **high** G1 depends on undeclared reference fixtures and on the last phase (§Goals G1; §Phasing) — G1 is "measured via the Fault Manifest + the detection audit," but the detection audit is CC-11 in **Phase 3**, so the headline falsifiable goal cannot be evaluated until the final phase ships; and the "reference pipeline + reference data-QA alert suite" it runs against are assumed into existence with no scope/ownership. *Fix:* state whether the reference pipeline + alert suite are build-scope or external givens, and add an interim G1 proxy that Phase 1 can validate without CC-11 (e.g., manual inspection of manifest vs. a known-brittle pipeline).

## Substance over theater — strong

Lean and earned. One role, one UJ — no persona theater. The Vision is product-specific (Fault Manifest, detection audit, missing-data/schema-drift, mixed-mode recoverability) and would not swap cleanly into another PRD. The differentiation claim is backed by a named competitive read (Gremlin / Chaos Mesh / Toxiproxy corrupt infra not data; Great Expectations validates but does not generate) — that is a real white-space argument, not template furniture. The thesis carries a cost basis ("new mutator strategies, not new infrastructure"). Counter-metrics CM1 (chaos must include subtle faults, not only glaring ones) and CM2 (faithful baseline stays recoverable in mixed mode) are substantive and non-obvious.

The one furniture risk is unbacked demand rhetoric.

### Findings
- **medium** Demand claims asserted without a cited source (§Problem) — "the #1 cited data-engineering pain (per market scan)" and "two highest-demand, least-served families" carry no reference to the scan, yet they justify the entire phase ordering (missing-data first *because* highest-demand). *Fix:* cite the market scan or downgrade to a hypothesis tied to OQ-1's forcing function.

## Strategic coherence — strong

The PRD has a thesis and bets on it: content chaos is the sharpest differentiation *and* the cheapest cluster to build, so it ships next. Every feature serves that arc — the two fault families (missing-data, schema-drift), the policy/manifest extensions that make them reproducible and auditable, and the detection audit that closes the eval loop. Phase ordering follows the thesis (cheapest + highest-demand first), not "what's easy." Success metrics validate the thesis (break a pipeline / coverage-within-margin / reproducible-and-auditable) rather than measuring vanity activity, and counter-metrics are present. This reads as a designed capability, not a backlog with headings.

The coupling worth noting (also flagged under Decision-readiness): the thesis's proof point — "prove whether the pipeline survives" — is CC-11, the last thing built, so the strategic payoff is back-loaded.

## Done-ness clarity — adequate (thin on CC-11 and mechanism verification)

Most FRs carry a testable consequence and — notably — the PRD avoids adjective hand-waving: no "handles gracefully," "reasonable performance," or "user-friendly" anywhere. CC-1/CC-3/CC-5/CC-6/CC-7/CC-8/CC-9/CC-10 each name a verifiable behavior (remove a configurable fraction of rows; gaps in a monotonic column; rename/drop/add/reorder; type/nullability flip; versioned delta a contract test can diff; manifest records row/column/fault-type; emit through existing exporters). The MCAR/MAR/MNAR definitions in CC-2 are statistically correct (MCAR = uniform/independent; MAR = conditioned on another observed column; MNAR = conditioned on the column's own value).

But three gaps will bite story creation:

1. **Mechanism "honored" is unfalsifiable as written.** G2 asserts "the missingness mechanism (MCAR/MAR/MNAR) is honored," but no FR states *how you verify* that a run labeled MAR is actually MAR and not MCAR. Statistically distinguishing them requires a stated test (e.g., missingness rate must correlate with the conditioning column above some threshold). Without it, "honored" is an adjective.
2. **CC-11 is not buildable as specified.** The detection audit's entire interface — how the consumer reports what it detected — is deferred to OQ-3. The concept is real (bidirectional manifest-vs-detection contract extending the Story 3.6 audit), but as a spec it's a placeholder until the format is decided.
3. **No per-FR acceptance criteria.** Every FR is a one-liner leaning on inherited SM margins (SM-7 ±2pp). Fine for a first cut; downstream will need each family's own accept condition.

### Findings
- **high** No verification method for the missingness mechanism (§G2; §CC-2) — "the mechanism is honored" has no testable definition distinguishing MCAR from MAR from MNAR. *Fix:* add an acceptance condition per mechanism (e.g., MAR: nullification probability must track the conditioning column; MNAR: must track the target column's own value; MCAR: independence within ±2pp).
- **medium** CC-11 detection-audit contract undefined (§CC-11; OQ-3) — the consumer-report format (results file? exit codes? alert log?) is open, so CC-11 cannot be storied yet. *Fix:* pick a minimal declared format for the first cut (even "a CSV of detected fault IDs") so Phase 3 has a buildable surface; keep richer formats as the OQ.
- **medium** CC-2 / CC-4 boundary blurs (§CC-2, §CC-4) — cell-level nullification (CC-2) and "null a subset of columns per affected row" (CC-4) overlap; MCAR at cell level can look identical to partial records. The stated distinction ("distinct from CC-2's cell-level pattern") is thin. *Fix:* pin the discriminator — CC-4 = row-scoped column-set nullification with a per-row column selection; CC-2 = independent per-cell draw.
- **medium** No per-FR acceptance criteria (§Functional Requirements) — all FRs are one-liners relying on inherited SM-7 margin. *Fix:* acceptable for this first cut, but add an acceptance line per family before story creation.

## Scope honesty — strong

Among the strongest dimensions. Out of Scope is explicit and does real work: streams/queues, API/OpenAPI-contract chaos, faithful generation, learned/generative missingness, and multi-table/whole-DB chaos are each named with their destination (PRD 3 / MVP / deferred). `[ASSUMPTION]` tags sit on the genuine inferences (CC-2 rule-based conditioning, CC-11 declared-format, single-table scope) and each roundtrips to an OQ. Open-items density — 4 Open Questions + ~3 assumptions — is exactly right for a pre-forcing-function first cut and would be a blocker only if this claimed green-light status, which it explicitly does not (frontmatter: "Fast-path first cut… pending the forcing function").

### Findings
- **low** No Assumptions Index despite the frontmatter promise (§frontmatter note vs. body) — the note advertises "[ASSUMPTION] tags + Open Questions," and the tags exist inline (CC-2, CC-11, Out-of-Scope multi-table) but there is no end-of-doc index to roundtrip against. *Fix:* add a short Assumptions Index; low effort, helps downstream extraction.

## Downstream usability — adequate

This PRD is chain-top (feeds architecture → stories). ID hygiene is clean: CC-1..CC-11 are contiguous, unique, and phase-mapped. The single UJ has a named protagonist ("the pipeline hardener") carrying context inline. But two things make standalone extraction harder than it should be:

- **No Glossary.** MCAR/MAR/MNAR are saved by inline parentheticals, but the load-bearing inherited nouns (Fault Manifest, Chaos Policy, Mutator, canonical Schema, run_mode, "faithful") are used without local definition — a reader without the MVP artifacts is stranded.
- **Dense unresolved cross-refs.** FR-11..16, SM-3/4/7, SM-C2, AD-3/4/9/10/11/12, NFR-4/5, and "the Story 3.6 manifest audit" all resolve only against external MVP artifacts, and some (SM-C2, Story 3.6, AD-12 run_mode) are cited without a gloss of what they are.

### Findings
- **medium** No Glossary on a chain-top PRD (whole doc) — domain nouns inherited from the MVP are used but not locally defined; MCAR/MAR/MNAR survive only via inline parentheticals. *Fix:* add a compact Glossary (or an explicit "inherits definitions from MVP PRD §X") so architecture/story extraction is self-contained.
- **low** Unglossed inherited cross-references (§NFR; §CC-11) — "Story 3.6 manifest audit," SM-C2, AD-12 run_mode are cited without a one-line what-it-is. *Fix:* one-clause gloss at first use, or a cross-ref table.

## Shape fit — strong

Correctly shaped as a technical capability spec for a single-operator role. One role, one UJ, FR-centric body, operational rather than user-experience metrics — this matches the rubric's "internal tool / single-operator" profile exactly. It is neither over-formalized (no persona padding, no UJ density for a solo operator) nor under-formalized (the FRs and SMs carry the weight UJs would in a consumer PRD). Brownfield references (FR-11..16, the AD set, existing exporters) are used correctly as the foundation this builds on, and new work is clearly distinguished by the CC- namespace.

## Mechanical notes

- **ID continuity:** CC-1..CC-11 contiguous and unique; phase mapping (Phase 1 = CC-1..4, CC-8..10; Phase 2 = CC-5..7; Phase 3 = CC-11) is internally consistent. Good.
- **Assumptions roundtrip:** inline `[ASSUMPTION]` tags (CC-2, CC-11, Out-of-Scope) each reference an OQ, but there is no end-of-doc Assumptions Index (see Scope finding).
- **Cross-ref resolution:** all inherited IDs (FR/SM/AD/NFR/Story) resolve only against external MVP artifacts — expected for a sequel PRD, but no local glossary safety net (see Downstream findings).
- **UJ protagonist:** UJ-1 has a named role protagonist carrying context inline. Fine for a capability spec.
- **Glossary:** absent (see Downstream).

---

### Finding counts by severity
- critical: 0
- high: 2
- medium: 5
- low: 2
