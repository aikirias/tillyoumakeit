---
title: TYMI — Contracts & Streaming (PRD 3)
status: draft
created: 2026-07-04
updated: 2026-07-04
note: Fast-path first cut, hardened by the reviewer gate (rubric + adversarial + license/feasibility, web-verified 2026-07-04). Phasing inverted to wedge-first.
---

# TYMI — Contracts & Streaming (PRD 3)

> Post-MVP PRD 3 (PRD 1 dev-env, PRD 2 content-chaos, **PRD 3 contracts & streaming**). The
> roadmap's heaviest cluster — sequenced last. **Reordered by the reviewer gate:** the
> differentiated wedge (contract-invalid payloads) is validated **broker-free first**; the
> queue/serialization plumbing comes after. New adapters/ports under the hexagonal core
> (AD-1/AD-2/AD-3); the 12 MVP ADs hold. Reuses the faithful generator (PRD 1/MVP) and the
> mutator engine (PRD 2/MVP). FR IDs use `SC-`.

## Problem

Modern stacks are **contract-driven** (OpenAPI, JSON-Schema, schema registries) and
**streaming** (Kafka, Pulsar). The sharp, unserved gap: **no tool generates *invalid* payloads
against a contract** to test consumer/endpoint resilience. Valid stream test-data (Confluent
Datagen), contract *mocking/validation* (Pact, MockServer, `jsonschema`/`openapi-core`), and
valid-instance fakers (JSON-Schema-faker) are all commodity — none deliberately produces
**contract-invalid** instances (schema violations, OOD, malformed) with a reproducible,
auditable manifest. Secondarily, teams want realistic synthetic **event streams** for dev and
stress-testing, which today means hand-rolled producers.

## Vision

Turn a **contract** (OpenAPI / JSON-Schema) into a stream of **valid + surgically-invalid
payloads**, reproducible and audited by the Fault Manifest — first to a file/stdout (any
validator or HTTP harness consumes it), then delivered to a **queue** (Kafka/Pulsar/RabbitMQ)
with proper serialization once the wedge is proven.

**Thesis:** the differentiator is **contract-invalid payload generation** — a pure function
`contract → payloads` that needs **no broker** to validate. Faithful stream test-data and
serialization/registry plumbing are commodity, so they come *after* the wedge, not before.

## Competitive framing (why this is a wedge)

| Tool | Does | Generates contract-*invalid* payloads? |
| --- | --- | --- |
| Confluent Datagen | valid Kafka test-data | no |
| Pact / MockServer | contract mocking + validation | no |
| `jsonschema` / `openapi-core` | validate an instance against a schema | no (validators — TYMI uses them as the **pass/fail oracle**) |
| JSON-Schema-faker | valid instances from a schema | no |
| **TYMI PRD 3** | **valid + surgically-invalid instances against a contract, auditable** | **yes** |

## Goals & Success Metrics

**G1 — Break a contract-bound consumer, broker-free (falsifiable, Phase 1).** Given a
reference OpenAPI/JSON-Schema contract, TYMI emits payloads to a file of which a configured
fraction are **contract-invalid**; a reference validator (`jsonschema`/`openapi-core`, the
oracle) **rejects exactly the invalid ones and accepts the valid ones**, matching the Fault
Manifest. No queue involved.
**G2 — Faithful delivery to a real queue (Phase 2).** TYMI emits to a Kafka topic with the
declared serialization; a reference consumer reads records back **faithful to the canonical
Schema mapping** (AD-10) with no silent field loss (CM2).
**G3 — Reproducible & auditable.** Same config+seed → identical **emit-boundary** sequence
(the ordered `(partition, key, value-bytes)` tuples) + identical Fault Manifest — **not**
byte-identical topic state (see NFR-C).

**Counter-metrics:** **CM1** invalid payloads must span *subtle* single-constraint violations,
not only gross malformations. **CM2** serialization round-trips the canonical Schema with no
field loss.

## Phasing / Roadmap

Inverted from the first cut: **wedge before plumbing.**

- **Phase 1 — Contract → valid/invalid payloads, broker-free.** Ingest a contract; generate
  valid payloads; generate **surgically-invalid** payloads via contract-aware mutators; emit
  to file/stdout; audit against the validator oracle. `SC-1, SC-2, SC-3`. No queue, no
  registry, no license risk.
- **Phase 2 — `StreamSink` (Kafka) + serialization + registry.** Deliver the payloads to a
  Kafka topic; serialize; integrate a schema registry. `SC-4, SC-5, SC-6`.
- **Phase 3 — Breadth (more queues) + faithful stream provisioning.** Pulsar + RabbitMQ sinks;
  let PRD 1's `provision` target a topic. `SC-7, SC-8`.

## Users & Journeys

**Two roles.** The **API developer** (tests a contract-bound endpoint/event schema) and the
**streaming engineer** (feeds a dev streaming env / stress-tests a consumer). **UJ-1:** point
TYMI at a contract, get valid + invalid payloads to a file, run them through the endpoint's
validator and see which invalid ones it wrongly accepts — then (Phase 2) flip the same
payloads onto a Kafka topic to stress the live consumer.

## Functional Requirements

### A. Contract wedge, broker-free (Phase 1)

- **SC-1 — Contract ingestion.** Ingest an **OpenAPI / JSON-Schema** contract and derive a
  canonical Schema (AD-10) from it — a contract is a schema source, like a DB table.
- **SC-2 — Valid payload generation.** Generate faithful payloads satisfying the contract
  (builds on TYMI's own generator + the schema mapping; no OSS generates schema instances).
- **SC-3 — Contract-aware invalid-payload chaos (the wedge, net-new).** Generate
  contract-*invalid* payloads by a **schema-aware mutator family** that reads the contract's
  constraints and **violates one surgically** (type, range, enum, required, format), at a
  configured rate, recorded in the Fault Manifest. Emit to file/stdout; validate against
  `jsonschema`/`openapi-core` as the pass/fail **oracle**. **Not a live-traffic proxy** — TYMI
  produces payloads; a harness sends them.

### B. Queue delivery (Phase 2)

- **SC-4 — `StreamSink` port + Kafka sink.** A new destination-adapter family (AD-2/AD-3,
  `tymi.sinks` entry points); emit to a Kafka topic. Clients are AD-9-permissive
  (`confluent-kafka`/`kafka-python`, Apache-2.0; verified).
- **SC-5 — Serialization.** Serialize from the canonical Schema to **Avro / JSON / Protobuf**
  with **no silent field loss** (CM2); canonicalized (sorted JSON keys / Avro canonical form)
  for determinism.
- **SC-6 — Schema-registry integration.** Register/resolve via the wire protocol shipped in
  the Apache-2.0 `confluent-kafka` serializers, against a **user-supplied** registry endpoint.

### C. Breadth (Phase 3)

- **SC-7 — Pulsar & RabbitMQ sinks.** Two more `StreamSink` adapters (`pulsar-client`
  Apache-2.0, `pika` BSD-3; verified).
- **SC-8 — Faithful stream provisioning.** PRD 1's `provision` can target a topic (a faithful
  dev *streaming* environment), now that a `StreamSink` exists.

## Non-Functional Requirements & Constraints

- **Hexagonal (AD-1/AD-2/AD-3):** `StreamSink` is a destination adapter; core imports no
  concretes; sinks are entry-point plugins.
- **AD-9 license (resolved for clients; a design rule for servers).** Every queue/
  serialization/contract client is **permissive** (web-verified 2026-07-04: confluent-kafka
  Apache-2.0 + librdkafka BSD-2, pulsar-client Apache-2.0, pika BSD-3, fastavro MIT, protobuf
  BSD-3, jsonschema MIT, openapi-core BSD-3). **The rule:** TYMI may *talk to* a broker or
  registry but must **not bundle/redistribute/auto-provision** a non-permissive *server* (the
  **Confluent Schema Registry server is Confluent Community License**, not OSI-permissive;
  RabbitMQ server is MPL-2.0). The reference registry is **Apicurio (Apache-2.0)**; the
  Confluent registry is a user-supplied endpoint only.
- **NFR-C Determinism at the emit boundary (not the broker).** Byte-identical topic state is
  **not honorable** (broker CreateTime, offsets, compression framing, retry reordering). The
  reproducibility SLA is TYMI's **emit boundary**: the deterministic ordered `(partition, key,
  value-bytes)` sequence + Fault Manifest, with timestamps set from the seed, the idempotent
  producer required, explicit partitions pinned, and canonical serialization.
- **Zero real values (AD-6/AD-7):** the leakage gate still applies to faithful stream output.
- **Canonical Schema (AD-10):** serialization maps from the canonical Schema, never raw dtypes.

## Out of Scope

- **A live-traffic fault-injection proxy** (latency/5xx on real traffic — Toxiproxy/Gremlin
  territory); TYMI generates payloads, it does not intercept live traffic.
- **CDC / change-stream synthesis and time-series / event-stream synthesis** — these are
  generator/temporal-modeling products, **not streaming features** (time-series was an
  MVP-deferred hard item). **Evicted to a future PRD (PRD 4 candidate)**, not smuggled here.
- **Faithful DB generation (PRD 1)** and **batch content-chaos (PRD 2)** — reused, not re-spec'd.
- **Consuming/profiling a live stream** — profiling stays batch/sample-based (OQ-4).

## Open Questions

- **OQ-1 (forcing function / first queue).** Which queue does a real team need first (Kafka
  assumed for Phase 2)? A concrete pull sets the Phase-2 target and could reorder vs PRD 2.
- **OQ-2 (serialization first).** Avro, JSON, or Protobuf first — driven by the target
  registry/environment.
- **OQ-3 (G1/G2 targets).** The invalid-payload fraction + margin for G1, and the Phase-2
  throughput target for G2.
- **OQ-4 (stream as source).** Do we ever *profile from* a live stream, or only *emit to* one?
