# Adversarial Review — TYMI PRD 3 (Streaming & Contracts)

**Reviewer stance:** hostile PM (Cagan/Torres). Job here is to kill or shrink this
before it eats a quarter. **Verdict up front: DO NOT BUILD AS SCOPED.** The PRD has
the right thesis (line 37) and then builds everything *except* the thesis first. It is
a plumbing project wearing a wedge's clothing.

Severity legend: **BLOCKER** (invalidates the plan) · **MAJOR** (must fix before
sequencing) · **MINOR** (fix in edit).

---

## F1 — BLOCKER — The PRD funds the commodity and defers the wedge. Sequencing is inverted.

The PRD states its own thesis explicitly:

> "the differentiated wedge is **invalid-payload-against-contract generation** (an
> unserved gap), not faithful stream test-data (commodity)." (line 37)

> "valid Kafka test-data (Confluent Datagen) and schema *validation* ... are
> commodity, but **deliberate malformed / OOD payload generation against a contract is
> unserved**." (lines 23–25)

Then Phase 1 (lines 61–63, SC-1..SC-4) builds `StreamSink` + Kafka + serialization +
schema-registry integration — i.e. **the commodity** — and Phase 2 (lines 64–66,
SC-5..SC-7) builds the wedge. The differentiator is gated behind the heaviest,
least-differentiated infra cluster.

The PRD even *admits* the inversion in the Thesis:

> "The real cost is serialization + schema-registry integration, so this is the
> heaviest cluster — sequenced last" (lines 38–40)

This is internally contradictory. The Vision/Thesis says serialization+registry is
"sequenced last," but Phasing puts serialization + registry in **Phase 1** (SC-3, SC-4,
lines 88–91). "Last" relative to the whole roadmap ≠ "first" within this PRD. Either
way, the falsifiable wedge (G2, "break a contract-bound consumer," lines 48–52) cannot
be tested until Phase 2, after you've paid the entire AD-9 license-risk tax (F5) and the
serialization-round-trip tax (CM2, line 57).

**Why this is fatal:** a wedge you can't validate until you've built the commodity is a
wedge you're betting on, not testing. If SC-5/6/7 is the reason to exist, it must be
Phase 1 and it must be reachable without Kafka.

**Fix:** Invert the phases. **Phase 1 = contract-in, invalid-payload-out to a file or
stdout** (SC-5 + SC-6 + SC-7). No broker, no registry, no serialization framing. Prove
teams want malformed-against-contract payloads and that the mutator engine can produce
*subtle* violations (CM1, line 55). Only if that lands do you fund the StreamSink
plumbing to deliver them over a wire.

---

## F2 — BLOCKER — The wedge does not need a queue at all. Phase 1 is unjustified infra.

SC-7 itself concedes the delivery mechanism is out of band:

> "**Not a live-traffic proxy** — TYMI produces payloads; the harness sends them."
> (lines 100–101)

If TYMI *produces payloads* and something else *sends them*, then the differentiated
value — "generate contract-invalid payloads" — is a **pure function: contract → set of
payloads**. That function's output can be validated against any JSON-Schema/OpenAPI
validator by writing to a file. A queue is a *transport*, orthogonal to whether the
payloads are good. Kafka + Avro + schema-registry (SC-1..SC-4) are entirely absent from
the causal chain that validates G2.

The market read reinforces this: JSON-Schema-faker, Pact, MockServer all operate on
files/HTTP with **no broker**. The genuinely unserved thing (invalid-against-contract)
lives in the same broker-free layer.

**Concrete challenge to the author:** name one hypothesis in G2 (lines 48–52) that a
file/HTTP first cut cannot falsify. There isn't one. "A configured fraction are
contract-invalid ... a reference consumer/validator rejects the invalid ones" — a
validator reads a file. Kafka adds latency to learning, not signal.

**Fix:** Cut SC-1..SC-4 from the critical path of the bet. StreamSink becomes a
*delivery adapter* added **after** the wedge is proven, exactly parallel to how batch
export was added after the generator existed.

---

## F3 — MAJOR — Scope sprawl: this is 4–5 products in one PRD. Even Phase 1 is 3 products.

Bundled here:

1. **Queue transport** (StreamSink: Kafka, then Pulsar + RabbitMQ — SC-1, SC-2, SC-8)
2. **Serialization** (Avro/JSON/Protobuf mapping from canonical Schema — SC-3)
3. **Schema-registry integration** (Confluent-compatible — SC-4)
4. **Contract ingestion + payload chaos** (OpenAPI/JSON-Schema → valid+invalid — SC-5/6/7)
5. **CDC change-stream synthesis** (Debezium-like envelopes — SC-9)
6. **Time-series/event-stream synthesis** (temporal correlation, seasonality — SC-10)

Items 1–3 are each independently large. "Serialize to Avro / JSON / Protobuf" (SC-3,
lines 88–89) is three serialization backends, each with its own registry-encoding
rules, wire framing, and round-trip test surface (CM2 demands *zero silent field loss*,
line 57 — that alone is a multi-week correctness project per format). SC-4 Confluent
registry integration is a network protocol + schema-evolution semantics. Calling
SC-1..SC-4 "Phase 1" hides at least three products behind one phase label.

**Fix:** One SPEC = one wedge. Phase 1 ships **one** serialization (JSON — no registry
needed, per OQ-2 the choice is env-driven and JSON is the zero-dependency default) and
**zero** registry. Avro/Protobuf/registry are their own phased items *only if* a real
Kafka+Avro user pulls them (OQ-1/OQ-4 are still unanswered — line 136, 142).

---

## F4 — MAJOR — "Deterministic ordering into a partitioned topic" is an overclaim. It is likely false.

NFR (lines 120–121):

> "the emitted sequence is seed-reproducible; ordering into a partitioned topic is
> deterministic for a given config."

And G3 (lines 52–53): "Same config+seed → identical emitted sequence."

**Seed-reproducible *emitted sequence* (what TYMI generates in-process): defensible.**
**Deterministic *ordering into a partitioned topic*: not something TYMI controls.** Once
records cross into Kafka:

- **Partition assignment** is by key-hash (or round-robin/sticky for null keys). Global
  ordering across partitions is *not defined* by Kafka — only per-partition ordering is.
  So "ordering into a partitioned topic" is undefined at the topic level regardless of
  TYMI's seed.
- **Async producers** batch and may reorder on the wire; retries after transient errors
  can reorder unless `max.in.flight.requests.per.connection=1` **and**
  `enable.idempotence=true`. The PRD names neither constraint.
- **Byte-identical reproducibility across a broker** is further undermined by
  producer-side timestamps, headers, and registry-assigned schema IDs (SC-4) embedded in
  the payload framing — none of which are seed-controlled.

The PRD's own G1 falsification test (lines 44–47) is "a reference consumer reads N
records back byte-faithfully to the canonical Schema mapping" — note it quietly scopes
determinism to the **canonical Schema mapping**, i.e. *decoded field values*, not
*topic ordering* or *wire bytes*. That is the honest claim. The NFR (line 121) and G3
overreach past it.

**Fix:** Downgrade the NFR to what's true and testable: *"The generated record sequence
and per-key partition assignment are seed-reproducible; TYMI does not and cannot
guarantee global topic ordering or wire-byte identity across a broker (Kafka semantics)."*
State the required producer config (`enable.idempotence=true`,
`max.in.flight=1`) as a constraint if per-partition ordering is a goal. Delete "identical
emitted sequence" as a topic-level claim.

---

## F5 — MAJOR — The AD-9 license risk is load-bearing AND unresolved. Phase 1 is blocked on an open question.

The PRD flags this itself, repeatedly and honestly:

> "Permissive-license deps (AD-9) — load-bearing here ... **This is the main AD-9 risk
> of the roadmap** (OQ-3)." (lines 118–119)

> SC-2: "client = `confluent-kafka` or `kafka-python` — **license must be verified
> permissive (AD-9)** before binding (OQ-3)." (lines 85–87)

OQ-3 (line 140) is **open**. So Phase 1's foundational adapter (SC-2 Kafka sink) is
gated on an unanswered license question — and `confluent-kafka` wraps `librdkafka`, and
Confluent's own Schema Registry client (implied by SC-4, line 91) has historically
shipped under the **Confluent Community License, which is NOT OSI-permissive**. This is
not a footnote; it can *veto the entire Phase 1 as specified*.

This is a second, independent reason not to put the plumbing first: **you'd be
sequencing the license-riskiest, most-vetoable work ahead of the work that actually
validates the product.** F1/F2's file-first inversion sidesteps OQ-3 entirely for the
wedge test — a file writer has no queue-client dependency.

**Fix:** Resolve OQ-3 *before* any StreamSink story is sized. Confirm specifically
whether the Confluent Schema Registry client and `librdkafka` clear AD-9. If they don't,
SC-2/SC-4 are re-scoped to permissive alternatives (`aiokafka`?) or cut. Until resolved,
StreamSink cannot be committed.

---

## F6 — MAJOR — SC-9 (CDC) and SC-10 (time-series) are separate products smuggled into Phase 3.

- **SC-10 time-series** (lines 108–109) is explicitly "**was an MVP-deferred item**" —
  temporal correlation + seasonality beyond MVP. Something the MVP deliberately deferred
  as too hard does not become free because a `StreamSink` now exists. Correlated temporal
  synthesis (seasonality, autocorrelation, drift) is a **generator-modeling problem**,
  not a streaming problem — it belongs to the faithful-generator line (PRD 1), not this
  PRD. It rode in on the word "stream."
- **SC-9 CDC** (lines 106–107) — "Debezium-like insert/update/delete change stream" —
  requires modeling *entity lifecycle over time* (a row's create→update→delete history
  with referential consistency), which is again a generator/state-modeling problem, plus
  Debezium envelope fidelity. That's its own PRD.

Both are parked in "Phase 3 — Additional queues + CDC + time-series" (line 69), a phase
that also absorbs Pulsar + RabbitMQ (SC-8). Phase 3 is a junk drawer: two transports +
two modeling products under one heading. This guarantees Phase 3 never ships coherently.

**Fix:** Remove SC-9 and SC-10 from this PRD. File them as candidate PRD-4 items
("Temporal & change-stream synthesis"). Phase 3 becomes purely "additional transports"
(SC-8, SC-11) — a homogeneous, sensible phase.

---

## F7 — MINOR — Buy-vs-build honesty: mostly good, one gap.

Credit where due: the PRD is unusually honest that valid-stream test-data (Datagen) and
schema *validation* (Registry/Conduktor) are commodity (lines 23–25) and scopes the
claim to invalid-against-contract. Good.

**The gap:** it does not confront the *closest* competitors to the actual wedge.
**Pact** (consumer-driven contract testing) and **MockServer** already let teams assert
consumer behavior against contracts, and **JSON-Schema-faker** already generates data
from a JSON-Schema (and can be coaxed into boundary/invalid cases). The PRD names none
of these three in the differentiation argument — it only benchmarks against Datagen and
Registry, which are the *streaming* commodities, not the *contract* ones. Since the wedge
is the contract side, the competitive framing benchmarks against the wrong shelf.

**Fix:** Add a differentiation paragraph vs Pact / MockServer / JSON-Schema-faker
specifically on the *invalid-and-subtle* axis (CM1, line 55): the claim must be "these
generate *valid* fixtures or assert *known* interactions; none systematically generate
*subtle contract-violating* payloads at a controlled rate with a reproducible Fault
Manifest." If that sentence can't be defended, the wedge isn't real.

---

## F8 — MINOR — G1 throughput target is undefined (OQ-5), yet G1 is called "falsifiable."

G1 (lines 44–47) is titled "falsifiable" but its throughput bar is "[ASSUMPTION] target
— OQ-5" (line 47, open at line 143). A goal with an unset threshold is not falsifiable.
Either set a number or drop throughput from G1's success criteria and keep only the
round-trip-fidelity clause (which *is* testable).

---

## Summary of required changes (in priority order)

1. **Invert phasing (F1) + prove the wedge broker-free (F2):** Phase 1 = SC-5/6/7 to
   file/HTTP. StreamSink demoted to a later delivery adapter.
2. **De-scope Phase 1 (F3):** one serialization (JSON), zero registry, until a real user
   pulls Avro/Protobuf/registry.
3. **Fix the determinism overclaim (F4):** scope to seed-reproducible *generation* +
   per-key partition assignment; disclaim topic-global ordering and wire-byte identity.
4. **Resolve OQ-3 before sizing any StreamSink story (F5):** the license veto is real
   (Confluent Community License is not permissive).
5. **Evict SC-9/SC-10 to a future PRD (F6):** CDC and time-series are modeling products,
   not streaming features.
6. **Fix competitive framing (F7)** and **set or drop the throughput target (F8).**

**Bottom line:** the PRD correctly *identifies* the wedge and then structurally
*protects the commodity*. Rebuild it around the pure function `contract → invalid
payloads`, validated without a broker, and treat every queue/serialization/registry line
as post-validation plumbing gated on OQ-3.
