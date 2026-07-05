# PRD Quality Review — TYMI Obfuscated Prod-Like Dev Environments (PRD 1)

## Overall verdict

A strong, disciplined capability spec: it has a real thesis ("kill the copy-prod-down habit; get consistency from a shared versioned Spec"), the four problem statements map cleanly to four goals to the FR blocks, and it earns its scope with an unusually honest Out-of-Scope section and genuinely open Open Questions. What's at risk is downstream mechanics rather than strategy: two fidelity FRs (FR-5/FR-6) and the fail-closed guardrail (FR-14) push their testable thresholds into Open Questions, the PRD reuses the MVP's FR-1…N numbers under a parallel namespace while cross-referencing "MVP FR-2/FR-9/FR-23," and there is no Glossary — all of which will bite a chain-top PRD feeding architecture and story creation. None of this undermines a go/no-go decision; it means a handful of FRs aren't yet story-ready.

## Decision-readiness — strong

A decision-maker can act on this. Trade-offs are stated as decisions, not smoothed to neutral: Option B (keyed pseudonymization / reversible traceability) is named and *rejected* in Out of Scope ("rejected; this PRD is irreversible synthesis only… consistency via shared spec (Option A)"), and distributed generation is explicitly deferred as "the extreme-tail escape hatch." Counter-metrics CM1–CM3 name what G1 must not break ("fast *but* leaks = failure"), which is the honest version of a speed goal. The four Open Questions (OQ-1…OQ-4) are real forks with the cost of each side surfaced — OQ-1 in particular ("Ship in phase 1, or land the full-rebuild path first…") flags the highest-risk item for a phasing decision rather than pretending it's settled.

The one softness: G1's own metrics are partly unfalsifiable — "self-service ratio (% provisioned with no handoff) **high**" and ticket volume "→ **~0**" have no threshold. This is a goal-level vagueness, not a buried decision, so it doesn't sink the dimension, but see the Strategic-coherence finding.

## Substance over theater — strong

Very little furniture. The PRD collapses personas to a single **role-agnostic** "self-service provisioner" and *argues* for it ("The role is defined by the job… not the title… The point is to remove the mandatory gatekeeping *handoff*, not to exclude anyone") — the opposite of persona theater. The Vision is product-specific and would not swap into a generic data-tool PRD (the "identical synthetic entities, aligning cross-team IDs for free" claim is particular to this design). NFRs carry real thresholds rather than boilerplate: NFR-A commits to "**megabytes to hundreds of terabytes**" with "**bounded, configurable memory footprint**… out-of-core / chunked," and NFR-B refuses a fake number ("There is no fixed absolute time cap — 'minutes' is a function of size and resources"). That refusal is the anti-theater move done right.

## Strategic coherence — strong

There is a clear thesis and the features follow from it. The Problem section's four bullets (Unrealistic / Incomplete / Unsafe / Inconsistent) — with "Unsafe (the sharp one)" explicitly flagged as the load-bearing pain — map one-to-one onto G3 / (whole-DB) / G2 / G4, and the FR blocks A–F are organized as an arc (introspect → generate → fixtures → consistency → safe provisioning → scale), not a backlog. Success metrics validate the thesis rather than measuring activity: G4's "byte-identical output across runs" and "0 manual ID-reconciliation tasks" test the actual bet (shared-spec consistency). Counter-metrics are present. MVP scope kind reads as problem-solving/platform and the scope logic matches.

### Findings
- **medium** G1 north-star metrics are not falsifiable (§ Goals & Success Metrics, G1) — "self-service ratio … **high**" and "ticket volume → **~0**" give no target, so the PRD's headline goal can't be scored. *Fix:* set a concrete threshold (e.g. "≥80% of provisions with zero handoff" and "copy-prod-down tickets = 0/quarter"), or state that the byte-identical/leakage SMs are the hard targets and G1's are directional.

## Done-ness clarity — adequate

Most FRs carry a testable consequence: FR-4 ("every FK resolves to a generated PK and no unique constraint is violated"), FR-7 ("no real sensitive value survives to any table"), FR-10 ("Generated rows never collide with fixture PK/unique keys"), FR-11 ("byte-identical output across runs, machines, and teams"), FR-16 (connected subset defined concretely, "Not a naive per-table `LIMIT`"). NFR-C and NFR-F are likewise verifiable. That's a solid backbone.

The gaps are concentrated in the fidelity and guardrail FRs, which is exactly where story creation will lean hardest. FR-5 and FR-6 both rest on "**within tolerance**" with the tolerance itself deferred to OQ-3 and to the Spec — an engineer can't yet write the pass/fail assertion for cross-table correlation. (It partially inherits MVP SM-1's "≥90% of columns pass," but FR-6's correlation tolerance has no inherited number.) FR-14 is the sharper one: "Refuse a destination **flagged/detected as production**" is the fail-closed guarantee, yet *how* production is detected is OQ-2 — so "done" for the PRD's most safety-critical FR is currently undefined. These are honestly flagged as Open Questions rather than hidden, which is why the dimension is adequate and not thin, but those OQs are blockers for the corresponding stories, not nice-to-haves.

### Findings
- **medium** FR-14's fail-closed guarantee has no defined trigger (§ FR-14 / OQ-2) — "flagged/detected as production" is the counter-metric CM2 safety net, but detection mechanism is an open question, so the FR isn't testable as written. *Fix:* resolve OQ-2 to at least a default mechanism (e.g. required explicit non-prod affirmation + deny-list) before this FR enters a story; keep richer detection as follow-up.
- **medium** FR-5/FR-6 tolerance is undefined inline (§ FR-5, FR-6, OQ-3) — "within tolerance" with no bound and (for FR-6) no inherited number means the acceptance test can't be written. *Fix:* state the tolerance metric + threshold (or point to the exact inherited SM), and note FR-6's correlation tolerance separately from FR-5's per-column tolerance.

## Scope honesty — strong

This is the PRD's strongest dimension. The Out of Scope section does real work: eight explicit exclusions, each with a *reason* and a pointer (PRD 2 for chaos, external scheduler for orchestration, "chunked design *allows* it later" for distributed, leakage gate not DP for privacy, FK-graph model excludes non-relational). Deferrals are named, not silent (FR-17 "a candidate for a later phase — see Open Questions"; distributed "Deferred"). De-scoping of Option B is done out loud.

The one convention gap: the PRD makes several inferences presented as settled fact — "role-agnostic," "minutes on a single runner" for small/medium DBs — without `[ASSUMPTION: …]` tags or an Assumptions Index, and there are no `[NOTE FOR PM]` callouts at the tension points (e.g. FR-17 phasing, prod-detection default). For a post-MVP PRD the open-items are well-managed via OQ-1…4, so this is low-severity, but the roundtrip discipline the rubric expects is absent.

### Findings
- **low** No `[ASSUMPTION]` tags / Assumptions Index despite inferences (§ Users & Journeys, NFR-B) — claims like "role-agnostic" and "minutes on a single runner" are inferences carried as fact with no index for downstream to challenge. *Fix:* tag the load-bearing inferences and add a short Assumptions Index, or state explicitly that these were user-confirmed.

## Downstream usability — adequate

This PRD is chain-top (feeds architecture, then stories), so traceability matters. FR IDs are contiguous and unique (FR-1…FR-17); NFRs are cleanly labeled (NFR-A…F plus inherited); the single UJ is well-formed; and the addendum correctly quarantines mechanism from requirements. Cross-references to the MVP (AD-1/AD-3, AD-6/AD-7, SM-1/2/4, NFR-4) are consistent even though they resolve to the other PRD and can't be checked here.

Two real frictions. First, there is **no Glossary**, yet the PRD introduces load-bearing domain nouns — "Spec," "fixture," "connected subset," "leakage gate," "out-of-core," "provision" — that architecture and story creation will source-extract; they're used consistently, but a chain-top PRD should pin them. Second, and sharper: the PRD **reuses the MVP's FR numbers under a parallel namespace** ("FR IDs are scoped to this PRD… They build on the MVP's shipped FR-1…FR-25") while simultaneously citing "MVP FR-2," "MVP FR-9," "MVP FR-23" *inside* FRs that themselves are the local FR-1, FR-4, FR-2. A reader seeing "FR-2" must disambiguate two different requirements. That is a live traceability hazard once these two PRDs are read together downstream.

### Findings
- **medium** FR-number namespace collides with the MVP (§ Functional Requirements preamble) — local FR-1…17 overlap MVP FR-1…25, and FRs cite "MVP FR-2/FR-9/FR-23" beside their own reused numbers, forcing disambiguation. *Fix:* prefix this PRD's IDs (e.g. `P1-FR-1`) or the MVP citations (`MVP:FR-2`) so a bare "FR-9" is never ambiguous across the roadmap.
- **medium** No Glossary for a chain-top PRD (§ whole doc) — "Spec," "connected subset," "fixture," "leakage gate," "out-of-core" are used consistently but never defined for downstream source-extraction. *Fix:* add a short Glossary; it also lets sections be pulled out standalone via terms rather than prose context.

## Shape fit — strong

The shape matches the product. This is an internal/open-source, single-operator-role capability spec, and the PRD treats it as one: a single role, one golden-path UJ, and operational/technical success metrics (byte-identical output, leakage-gate pass, memory footprint) rather than forced consumer-style UX journeys. It is neither over-formalized (no manufactured persona set or UJ-per-feature padding) nor under-formalized (the one UJ that carries the end-to-end value story — CI/DAG trigger, credential isolation, fixtures, cross-team join — is present and load-bearing). The explicit reasoning about role ("Governance lives in the versioned Spec (reviewed like code), not in a gatekeeper person") shows the shape was chosen, not defaulted into.

## Mechanical notes

- **Glossary:** absent (see Downstream finding). Domain nouns are otherwise used consistently — no case/plural drift observed.
- **ID continuity:** FR-1…FR-17 contiguous and unique within the PRD; NFR-A…F clean. No gaps or duplicates *inside* this PRD. The cross-PRD FR-number reuse (Downstream finding) is the one continuity hazard.
- **Assumptions Index roundtrip:** no `[ASSUMPTION]` tags and no index; nothing to roundtrip (see Scope finding).
- **`[NOTE FOR PM]` callouts:** none present; tensions are instead carried as OQ-1…OQ-4, which is acceptable for this PRD's stakes.
- **UJ protagonist:** UJ-1's protagonist is an unnamed "practitioner." Acceptable here because the role is deliberately singular and role-agnostic, but a name would let the UJ stand fully alone.
- **Cross-refs to MVP** (ADs, SMs, NFRs, FRs): internally consistent; not verifiable within this document.

### Finding counts
- critical: 0
- high: 0
- medium: 4
- low: 1
