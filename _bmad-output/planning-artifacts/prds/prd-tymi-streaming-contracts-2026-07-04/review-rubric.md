# PRD Quality Review — TYMI Streaming & Contracts (PRD 3)

## Overall verdict

This is a strong, honest direction-setting PRD for the roadmap's heaviest and last
cluster. The thesis is genuinely differentiated (invalid-payload-against-contract is the
unserved wedge; faithful stream test-data is named as commodity), the phasing is sane
(build the sink/serialization substrate → validate the wedge on one queue → breadth), and
the load-bearing risk (AD-9 dependency licenses) is flagged repeatedly and correctly rather
than smoothed over. What's at risk is not honesty but altitude: this is a first-cut *direction*
doc, not a build-ready spec — every binding decision (first queue, serialization order,
registry, throughput number, dependency licenses) is deferred to an Open Question, one clause
of G1 has no number, and the Phase 2/3 FRs lack acceptance bounds. All of that is appropriate
to the declared "fast-path first cut" and is honestly signposted, so the PRD is decision-ready
for *"pursue this cluster, in this order"* — just not yet for *"start building Phase 1."*

## Decision-readiness — strong

The PRD states its decisions as decisions and names what each costs. The thesis (§Vision)
commits to a specific wedge and explicitly concedes the rest is commodity ("the differentiated
wedge is invalid-payload-against-contract generation … not faithful stream test-data
(commodity)"). It states the sequencing rationale ("the real cost is serialization +
schema-registry integration, so this is the heaviest cluster — sequenced last"). Trade-offs are
surfaced, not buried: the Out-of-Scope section actively distinguishes TYMI from Toxiproxy/Gremlin
("TYMI generates payloads, it does not intercept live traffic"). The Open Questions are genuinely
open and one (OQ-3, licenses) is potentially blocking. Pushback would find its objection
acknowledged, not dodged.

The one real weakness: the doc defers *all* of its load-bearing calls (first queue OQ-1,
serialization OQ-2, registry OQ-4, throughput OQ-5, licenses OQ-3) to the forcing function.
That is honest and declared in the frontmatter, but a reader should not mistake this for a
green-light-to-build artifact.

### Findings
- **low** OQ-6 ("stream as source") reads as confirm-my-assumption, not open (§Open Questions / §Out of Scope) — it already carries an `[ASSUMPTION] out of scope; profiling stays batch/sample-based`. It's honestly tagged, so this is fine, but it's the one OQ with a pre-baked answer. *Fix:* keep, or restate as "confirm: profiling stays batch — any pull for stream-source profiling?"

## Substance over theater — strong

Nothing here reads as furniture. The differentiation claim is earned and specific: it names the
commodity incumbents it is *not* competing with (Confluent Datagen for valid Kafka data; Schema
Registry / Conduktor for validation) and the exact gap it targets (deliberate malformed/OOD
generation against a contract). No persona theater — two roles (streaming engineer, API developer)
and a single UJ, both of which drive the wedge rather than decorate it. The Vision is
product-specific and could not be pasted into another PRD. Counter-metrics point at real failure
modes: CM1 (subtle vs. gross contract violations) and CM2 (serialization dropping a field silently)
are exactly the ways this feature would be quietly useless.

### Findings
- **low** Market-scan claims are asserted, not cited, inside this PRD (§Problem: "valid Kafka
  test-data … and schema validation … are commodity, but deliberate malformed … is unserved").
  Load-bearing to the whole thesis. *Fix:* one cross-ref to the market-scan artifact so the wedge
  claim is traceable, not taken on faith.

## Strategic coherence — strong

The PRD has a thesis and the features serve it. The phasing is the coherence proof: Phase 1 builds
the `StreamSink` + serialization substrate (the "commodity" emit path), Phase 2 delivers the actual
wedge (contract-invalid payload generation, reusing the PRD-2 mutator engine), Phase 3 is breadth
(more queues, CDC, time-series). A superficial read might object that the differentiated wedge lands
in Phase 2, not first — but you cannot emit contract-chaos to a queue without a sink and
serialization, and the PRD says so ("the real cost is serialization"). So Phase 1 is a necessary
substrate, not a mis-prioritized easy-first. The success metrics validate the thesis rather than
measure activity: G2 *is* the wedge metric (break a contract-bound consumer with a controlled
invalid fraction), and CM1/CM2 guard its quality. "One queue first, then contract chaos, then
breadth" is a defensible risk-retiring order.

## Done-ness clarity — adequate

Split by phase. Phase 1 / near-term is reasonably testable: G1's round-trip clause ("a reference
consumer reads N records back byte-faithfully to the canonical Schema mapping"), G2's accept/reject
expectation, G3's seed-reproducibility, and CM2 ("a 'valid' payload that drops a field is a
failure") each name a verifiable consequence. SC-3 ("no silent field loss") and SC-7 ("at a
configured rate, recorded in the Fault Manifest") carry testable conditions.

But two gaps keep this from "strong," and this is the dimension story creation leans on hardest:

### Findings
- **medium** G1's throughput clause has no number (§Goals, G1): "Median throughput ≥ a target on a
  reference broker `[ASSUMPTION target — OQ-5]`." Half of a stated *falsifiable* goal is currently
  unfalsifiable — you cannot fail a bound that doesn't exist. Honestly tagged to OQ-5, so this is a
  known hole, but G1 should not be described as falsifiable until the number lands. *Fix:* land a
  provisional target (even an order-of-magnitude floor) so G1 can fail, or split the throughput
  clause into a separate, explicitly-deferred SM.
- **medium** Phase 2/3 FRs lack acceptance bounds (§FRs B/C). SC-5 ("derive a canonical Schema from
  [the contract]") — done = what mapping coverage? SC-9 ("a Debezium-like envelope") — which fields
  constitute conformant? SC-10 ("seasonality beyond the MVP's basic seasonality") — "beyond" is
  unbounded. Appropriate for a fast-path cut of deferred phases, but these are direction, not
  acceptance-ready; a second pass is required before those phases enter story creation. *Fix:* note
  explicitly that SC-5..SC-11 are capability sketches pending their phase's design pass.
- **low** SC-6 ("generate faithful payloads that satisfy the contract") has no criterion of its own
  beyond "satisfy" — carried implicitly by CM2's round-trip guard. Acceptable, but worth an explicit
  "validates against the contract's own validator" consequence.

## Scope honesty — strong

Omissions are explicit and do real work. The Out-of-Scope section draws the sharp boundary
(no live-traffic fault-injection proxy — the Toxiproxy/Gremlin line; faithful DB gen and batch
chaos reused-not-respecified; consuming/replaying real streams). `[ASSUMPTION]` tags sit on the
genuine inferences (Kafka client choice, Confluent-first registry, stream-as-source out of scope).
The frontmatter declares the altitude up front. Open-items density is high (6 OQs + ~4 assumptions)
but that is correct for a declared direction-setting first cut and would only be a blocker on a
green-light PRD, which this explicitly is not.

### Findings
- **low** The frontmatter promises "`[ASSUMPTION]` tags + Open Questions," but the inline
  `[ASSUMPTION]` tags (G1 throughput, SC-2 client, SC-4 registry, Out-of-Scope stream-source) are
  never collected into an Assumptions Index. Roundtrip is unverifiable at a glance. *Fix:* add a
  short Assumptions Index so every inline tag has an indexed home.

## Downstream usability — adequate

This PRD feeds architecture → stories, so traceability matters. It mostly holds: SC-1..SC-11 are
contiguous and unique; G1-G3 / CM1-CM2 are clean; cross-refs to AD-1/2/3/4/6/7/9/10/11 resolve
against the architecture spine, and the inherited SM-3/SM-4/SM-C2 references resolve against the
MVP PRD (both verified during this review). Domain nouns (`StreamSink`, canonical Schema, Fault
Manifest, contract) are used consistently. Friction points:

### Findings
- **medium** No Glossary. `StreamSink`, `Fault Manifest`, canonical Schema, and "contract" are
  defined inline or inherited from sibling PRDs rather than collected. For a chain-top PRD, a story
  author must reconstruct these from context. *Fix:* add a short Glossary (or explicit "inherits
  Glossary from MVP PRD + PRD 2, adds: StreamSink").
- **low** G3 and CM1 inherit their validating metrics (SM-3/4, SM-C2) from the MVP PRD by reference
  only. They resolve, but a story author cannot source-extract G3's done-ness without opening a
  second document. *Fix:* inline the one-line definition alongside the inherit reference.
- **low** Namespace inconsistency: this PRD uses G1-G3 / CM1-CM2 while the MVP PRD uses SM-N.
  Harmless, but a reader tracing metrics across the roadmap meets two schemes. *Fix:* note the
  mapping, or align namespaces.

## Shape fit — strong

Correctly shaped as a technical capability spec for an open-source, developer-operated tool. UJ
density is kept light (two roles, one load-bearing UJ that demonstrates the wedge workflow), FRs
are capability-oriented, and the success metrics are operational (throughput, byte-faithful
round-trip, seed-reproducibility) rather than user-engagement vanity — all appropriate to the
product type. Not over-formalized (no UJ theater for a single-operator tool) and not
under-formalized (the one UJ carries the differentiating flow). Good fit.

## Mechanical notes

- **Cross-refs (verified):** AD-1/2/3, AD-4/11, AD-6/7, AD-9, AD-10 all defined in
  `architecture-tymi-2026-07-01/ARCHITECTURE-SPINE.md`; SM-3, SM-4, SM-C2 defined in
  `prd-tymi-2026-07-01/prd.md`. All resolve.
- **ID continuity:** SC-1..SC-11 contiguous/unique; G1-G3, CM1-CM2, OQ-1..OQ-6, UJ-1 clean. OQ
  references from body (OQ-3 at SC-2, OQ-4 at SC-4, OQ-5 at G1, OQ-6 at Out-of-Scope) all resolve;
  OQ-1/OQ-2 are defined but not cited inline (acceptable — they gate the forcing function, not a
  specific FR).
- **Assumptions Index:** absent — see Scope-honesty finding. ~4 inline `[ASSUMPTION]` tags, uncollected.
- **UJ protagonist:** UJ-1 has a role protagonist ("an engineer") carrying context inline. Adequate
  for a capability spec.
- **AD-9 load-bearing (task-flagged):** honestly handled — stated in the thesis ("heaviest cluster"),
  the NFR section ("load-bearing here … the main AD-9 risk of the roadmap"), and OQ-3. This is a
  strength, not a defect. One improvement: SC-2 names `confluent-kafka`/`kafka-python` and SC-8 names
  Pulsar/RabbitMQ clients without even a preliminary license lean; the PRD could carry a provisional
  note (the named Kafka clients are in fact Apache-2.0/BSD-licensed) so OQ-3 is a verification step,
  not an open-ended blocker.
