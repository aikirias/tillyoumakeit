---
stepsCompleted: ['step-01', 'step-02', 'step-03']
inputDocuments:
  - _bmad-output/planning-artifacts/prds/prd-tymi-streaming-contracts-2026-07-04/prd.md
  - _bmad-output/planning-artifacts/architecture/architecture-tymi-contracts-streaming-2026-07-05/ARCHITECTURE-SPINE.md
---

# PRD 3 — Contracts & Streaming epics & stories

Turn a contract (OpenAPI / JSON-Schema) into valid + surgically-invalid payloads, then deliver
them to a queue. Architecture: `architecture-tymi-contracts-streaming-2026-07-05/` (AD-35..43 over
inherited AD-1..34). **The wedge (Phase 1) is broker-free** — the differentiator ships and is
falsifiable before any queue plumbing. New deps are permissive (AD-9, web-verified 2026-07-05:
openapi-core 0.23.1 BSD-3, pulsar-client 3.12.0 Apache-2.0, jsonschema/fastavro MIT, protobuf/pika
BSD-3, confluent-kafka Apache-2.0). Each story runs the full 3-layer `bmad-code-review` gate before
`done`; build/test in the devcontainer; code/artifacts in English.

## Requirements inventory

**FRs (from the PRD):** SC-1 contract ingestion · SC-2 valid payload generation · SC-3
contract-invalid payload chaos (the wedge) · SC-4 `StreamSink` port + Pulsar sink · SC-5
serialization (JSON/Avro/Protobuf) · SC-6 Pulsar in-broker schema registry · SC-7 Kafka + RabbitMQ
sinks · SC-8 faithful stream provisioning.

**Goals:** G1 break a contract-bound consumer broker-free (the oracle rejects exactly the invalid
set) · G2 faithful delivery to a real queue (round-trip, zero field loss) · G3 reproducible at the
**emit boundary**. **Counter-metrics:** CM1 invalid payloads span *subtle*/boundary single-constraint
violations · CM2 serialization round-trips with no field loss.

**Binding invariants (spine):** AD-35 contracts are a **nested** domain (`ContractSchema` +
`Payload`), never a stretched flat Schema; canonical normal form (`$ref` as named nodes, bounded
cycle unroll, canonical combinator order); **constraint-only leaf generation is net-new** (a contract
has no Profile — reuse is the Faker overlay + engine patterns, not marginals) · AD-36 a violation is
**document-level** (fails closed on `oneOf`/`anyOf`/`if-then`), exactly one surgical violation per
invalid payload, CM1 subtle/boundary · AD-37 payload fault key = `(payload_index, JSON-pointer,
constraint)` with defined pointer rules · AD-38 the validator is an **independent** oracle in `eval/`,
never in the generation path · AD-39 `StreamSink` is **write-only** (`tymi.sinks`), separate from the
bidirectional `EngineAdapter` · AD-40 determinism at the **emit boundary** (partition =
`payload_index mod N`, seed-derived key), not broker state · AD-41 serde canonical, zero field loss,
open-content → JSON-only/map catch-all · AD-42 talk-to but don't-bundle a non-permissive server ·
AD-43 G2 = emit-boundary round-trip check · hexagonal + import-linter (add `tymi.contracts`,
`tymi.sinks`, `tymi.serde` to the forbidden-for-core set).

### FR coverage map

| FR / Goal | Story | AD |
| --- | --- | --- |
| SC-1 | SC1.1 | AD-35 |
| SC-2 | SC1.2 | AD-35 |
| SC-3 (mutators) | SC1.3 | AD-36, AD-37 |
| SC-3 (oracle), G1, CM1 | SC1.4 | AD-38 |
| SC-5, CM2 | SC2.1 | AD-41 |
| SC-4, G3 | SC2.2 | AD-39, AD-40 |
| SC-6 | SC2.3 | AD-42 |
| G2 (round-trip) | SC2.1/SC2.2 (AC) | AD-43 |
| SC-7 | SC3.1 | AD-39, AD-42 |
| SC-8 | SC3.2 | AD-39, AD-41, AD-43; AD-6/AD-7 |

---

## Epic SC1 — Phase 1: The contract wedge, broker-free

The differentiator — valid + surgically-invalid payloads to a file, judged by an independent
validator oracle. No queue, no registry, no license risk. Sequenced so the nested `ContractSchema`
(foundational) lands before generation or mutation.

### Story SC1.1: Contract ingestion → `ContractSchema`

As an API developer, I want an OpenAPI/JSON-Schema contract compiled into a canonical nested schema,
so that generation and mutation have one unambiguous representation to work from (SC-1, AD-35).

**AC.** `NEW contracts/ingest.py` + `EXTEND domain/artifacts.py` (`ContractSchema`, `Payload`):
ingest an OpenAPI 3.0/3.1/3.2 or JSON-Schema contract (via `openapi-core`/`jsonschema`) into a
**`ContractSchema`** — nested, constraint-bearing, in a **canonical normal form**: `$ref` kept as
**named nodes** (never inlined), a cyclic/recursive `$ref` handled by a **bounded unroll depth `N`**,
`oneOf`/`anyOf`/`allOf` in a **canonical order**. Two ingestions of the same contract produce the
**same tree** (so downstream JSON-pointers and serialization agree). The flat canonical `Schema`
(AD-10) is untouched. `tymi.contracts` added to the import-linter forbidden-for-core set. Pure-core +
unit tests over nested/recursive/combinator fixtures.

### Story SC1.2: Valid payload generation

As an API developer, I want faithful payloads that satisfy the contract, so that I have a valid
baseline to corrupt and to feed a consumer (SC-2, AD-35).

**AC.** `NEW contracts/generate.py`: walk the `ContractSchema` tree and emit a valid **`Payload`**
(nested JSON). A **leaf scalar** is drawn by the **Faker overlay** (`fake_values`) where a
format/name heuristic applies, **else by the net-new deterministic constraint-derived draw** fixed by
the spine (a defined constraint-satisfying value per type/format/range/enum — **not** a Profile
marginal, since a contract has no Profile), so payload bytes are builder-independent and reproducible
for a given seed (AD-4/AD-11). Every generated payload validates clean against the oracle (SC1.4).
Depends on SC1.1.

### Story SC1.3: Contract-invalid `PayloadMutator` family

As an API developer, I want payloads that violate the contract in exactly one surgical way, so that I
can test whether a consumer wrongly accepts them (SC-3, AD-36, AD-37 — the net-new wedge).

**AC.** `NEW ports` entry (`PayloadMutator`) + `NEW contracts/payload_mutators/`: a family discovered
via the **`tymi.payload_mutators`** entry group (AD-3 pattern), `apply(payload, contract, *, rng) ->
(Payload, FaultManifest)`. Each invalid payload carries **exactly one document-invalidating
violation** (type / range / enum / required / format / nesting) at a configured rate; the mutator
**fails closed** on `oneOf`/`anyOf`/`if-then`/`allOf`-alternative targets unless the flip is provably
document-invalidating (so an "invalid" payload can't accidentally stay valid). Per **CM1**, the family
spans **subtle/boundary** near-misses (off-by-one `minimum`, one extra enum char), not only gross
malformations. Each fault is recorded by **`(payload_index, JSON-pointer, constraint)`** (AD-37,
pointer rules: `required`→parent object, `minItems`/`maxItems`→array, per-item→index). Deterministic;
manifest-merged like the tabular engine. Depends on SC1.2.

### Story SC1.4: Validator oracle + G1

As an API developer, I want an independent validator to confirm which emitted payloads are actually
invalid, so that G1 (the oracle rejects exactly the injected invalid set) is falsifiable (SC-3,
AD-38, G1).

**AC.** `NEW eval/contract_oracle.py` (chaos run_mode, AD-12): validate each emitted payload with
`jsonschema`/`openapi-core` as an **independent oracle** — the producer (SC1.2/SC1.3) never imports
it and the oracle never mutates (separation of powers). Emit payloads to **file/stdout**; the oracle
**rejects exactly** the manifest's invalid set and **accepts** the valid set (**G1**), the realized
invalid fraction within the inherited **±2 pp** margin. A mismatch (an invalid payload the oracle
accepts, or vice-versa) fails the run and names the `(payload_index, JSON-pointer)`. Depends on
SC1.3.

---

## Epic SC2 — Phase 2: Queue delivery (Pulsar) + serialization + registry

Deliver the payloads to a real Pulsar topic, serialized in any of the three formats, with
emit-boundary determinism and zero field loss. Pulsar first keeps the whole phase license-clean
(AD-42).

### Story SC2.1: Serialization (`serde`) — JSON / Avro / Protobuf

As a streaming engineer, I want the canonical schema serialized to any of three formats with no field
loss, so that I can feed whatever a consumer expects (SC-5, AD-41, CM2, AD-43).

**AC.** `NEW serde/`: serialize to **JSON, Avro, and Protobuf** from the **schema-of-record** (the
flat `Schema` for tabular streams; the `ContractSchema` for payloads), **canonicalized** (sorted JSON
keys / Avro canonical form / deterministic Protobuf field order) so emit-boundary bytes are stable
(AD-40). **CM2:** a declared field that would be dropped on round-trip **fails closed**. Nested↔closed-world
rules: **open content** (`additionalProperties: true`) serializes **JSON-only** (or a declared
`map<string, …>` catch-all), never a silent drop; **`oneOf` → union** uses the canonical branch order
(AD-35). **G2 round-trip (AD-43):** deserializing the emitted `value_bytes` back through `serde`
reconstructs the record field-for-field vs the schema — verified with no live broker.
`tymi.serde` added to the forbidden-for-core set. Depends on SC1.1 (ContractSchema).

### Story SC2.2: `StreamSink` port + Pulsar sink

As a streaming engineer, I want to emit the payloads onto a Pulsar topic deterministically, so that I
can stress a live consumer reproducibly (SC-4, AD-39, AD-40, G3).

**AC.** `NEW ports` entry (`StreamSink`, **write-only** — no introspect/sample) + `NEW
sinks/pulsar.py` (entry group **`tymi.sinks`**, `pulsar-client` Apache-2.0): emit an **ordered
sequence of `(topic, partition, key, value_bytes)`**. **Emit-boundary determinism (AD-40):**
timestamps **seed-derived** (not wall-clock), idempotent producer enabled, **partition =
`payload_index mod partition_count`** (never broker key-hash), record **key** = the declared natural
key else **seed-derived `f(seed, payload_index)`** (never null). The reproducible unit is the ordered
`(partition, key, value_bytes)` sequence + manifest — **not** topic state. `tymi.sinks` added to the
forbidden-for-core set. Depends on SC2.1.

### Story SC2.3: Pulsar in-broker schema registry

As a streaming engineer, I want schemas registered/resolved against Pulsar's native registry, so that
a consumer can deserialize without a separate registry server (SC-6, AD-42).

**AC.** In `sinks/pulsar.py`: register/resolve the serialization schema against **Pulsar's built-in
schema registry** (part of the Apache-2.0 broker) — so Phase 2 carries **zero Confluent Community
License** dependency. TYMI links only the permissive client and connects to a **user-supplied**
Pulsar endpoint; it never bundles/auto-provisions a registry server (AD-42). Depends on SC2.2.

---

## Epic SC3 — Phase 3: Breadth (Kafka + RabbitMQ) + faithful stream provisioning

More sinks, and let PRD 1's `provision` target a topic — a faithful dev *streaming* environment.

### Story SC3.1: Kafka + RabbitMQ sinks

As a streaming engineer, I want Kafka and RabbitMQ sinks too, so that TYMI covers the common brokers
(SC-7, AD-39, AD-42).

**AC.** `NEW sinks/kafka.py` (`confluent-kafka` Apache-2.0) + `sinks/rabbitmq.py` (`pika` BSD-3): two
more `StreamSink` adapters (`tymi.sinks`), same write-only contract + emit-boundary determinism
(AD-39/AD-40). The Kafka sink brings the **user-supplied** Confluent/Apicurio registry path (a
permissive client to a user-supplied endpoint); the RabbitMQ **server** is MPL-2.0 — talked-to, never
bundled (AD-42). Depends on SC2.2 (the port) + SC2.1 (serde).

### Story SC3.2: Faithful stream provisioning

As a streaming engineer, I want PRD 1's `provision` to target a topic, so that I can spin up a
faithful dev *streaming* environment from a Spec (SC-8, AD-39/AD-41/AD-43, AD-6/AD-7).

**AC.** `EXTEND provision/pipeline.py`: a **new `StreamSink` branch** (not a swap — the sink signature
differs from `EngineAdapter.load`) lets `provision` emit a faithful whole-DB dataset to a topic,
**row-per-message**. The **leakage gate (AD-6/AD-7) runs before `serde`** on this faithful path (zero
real values on the wire). Emit-boundary determinism (AD-40) and G2 round-trip faithfulness (AD-43)
hold. Depends on SC2.2 + SC2.1.

---

## Deferred (out of scope for PRD 3)

- **CDC / change-stream + time-series / event-stream synthesis** — evicted to a future PRD (PRD 4
  candidate); generator/temporal products, not streaming features.
- **A live-traffic fault-injection proxy** — TYMI produces payloads; a harness sends them.
- **Profiling *from* a live stream** — `StreamSink` is emit-only (OQ-4); a stream source is a future
  PRD.
- **Contract dialects beyond OpenAPI 3.0/3.1/3.2 + JSON-Schema** (GraphQL, gRPC, Avro-IDL-as-contract)
  — the `ContractSchema` seam allows them; not built now.
- **Cross-payload statistical/temporal correlation** — payloads are independent draws in PRD 3.
