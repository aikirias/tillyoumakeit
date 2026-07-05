---
title: PRD 3 (Streaming & Contracts) — Feasibility + OSS-License Review
reviewer: staff-engineer feasibility + license review
date: 2026-07-04
verified_via: live web search (PyPI / GitHub LICENSE files), current as of 2026-07-04
constraint_under_test: AD-9 (permissive-only deps — MIT / Apache-2.0 / BSD / LGPL-dynamic; BUSL & infecting-copyleft excluded)
---

# PRD 3 — Feasibility & License Review

Scope: the AD-9 verdict on every queue client, serializer, schema-registry, and
contract-ingestion library named or implied by SC-1..SC-11, plus feasibility
risk flags on determinism (SC/AD-4/AD-11), schema-registry lift (SC-4), and
contract-invalid payload generation (SC-7).

**Bottom line:** every *client-side* library TYMI would depend on is AD-9-safe
(permissive). The one genuine AD-9 trap is **server-side, not a Python dep**: the
**Confluent Schema Registry server is Confluent Community License (source-available,
NOT permissive)**. TYMI only ships the *client*, so binding `confluent-kafka` is
fine — but any plan to bundle, redistribute, or "provision a reference registry"
must use an Apache-2.0 registry (Apicurio), not Confluent's. See Verdicts.

---

## 1. License table (verified)

| Library (role) | License | Source |
|---|---|---|
| **`confluent-kafka`** (Kafka client, Python) | **Apache-2.0** | [PyPI](https://pypi.org/project/confluent-kafka/) · [GitHub confluentinc/confluent-kafka-python](https://github.com/confluentinc/confluent-kafka-python) |
| **`librdkafka`** (C lib under confluent-kafka) | **BSD-2-Clause** | [GitHub confluentinc/librdkafka](https://github.com/confluentinc/librdkafka) |
| **`kafka-python`** (pure-Python Kafka client) | **Apache-2.0** | [GitHub dpkp/kafka-python LICENSE](https://github.com/dpkp/kafka-python/blob/master/LICENSE) |
| **`aiokafka`** (async Kafka client) | **Apache-2.0** | [GitHub aio-libs/aiokafka LICENSE](https://github.com/aio-libs/aiokafka/blob/master/LICENSE) |
| **`pulsar-client`** (Pulsar client, Python) | **Apache-2.0** | [PyPI](https://pypi.org/project/pulsar-client/) · [GitHub apache/pulsar-client-python](https://github.com/apache/pulsar-client-python) |
| **`pika`** (RabbitMQ/AMQP client) | **BSD-3-Clause** | [PyPI](https://pypi.org/project/pika/) · [GitHub pika/pika](https://github.com/pika/pika) |
| **`aio-pika`** (async RabbitMQ client) | **Apache-2.0** | [PyPI](https://pypi.org/project/aio-pika/) |
| **`fastavro`** (Avro ser/deser) | **MIT** | [GitHub fastavro/fastavro](https://github.com/fastavro/fastavro) · [PyPI](https://pypi.org/project/fastavro/) |
| **`avro`** (Apache Avro reference Python lib) | **Apache-2.0** | Apache Software Foundation project ([lists.apache.org](https://lists.apache.org/thread/7zszzcdj6lm1txch1s5nfftlw864nmqy)) |
| **`protobuf`** (Google Protobuf runtime, Python) | **BSD-3-Clause** | [PyPI protobuf](https://pypi.org/project/protobuf/) |
| **`jsonschema`** (JSON-Schema validator) | **MIT** | [PyPI jsonschema](https://pypi.org/project/jsonschema/) |
| **`confluent-kafka[avro]` / `SchemaRegistryClient`** (registry *client* + Avro/JSON/Protobuf serializers) | **Apache-2.0** (part of confluent-kafka-python) | [confluent-kafka-python](https://github.com/confluentinc/confluent-kafka-python) |
| **`openapi-core`** (OpenAPI ingest/validate) | **BSD-3-Clause** | [PyPI openapi-core](https://pypi.org/project/openapi-core/) |
| **`datamodel-code-generator`** (schema→model codegen) | **MIT** | [PyPI](https://pypi.org/project/datamodel-code-generator/) · [GitHub koxudaxi/datamodel-code-generator](https://github.com/koxudaxi/datamodel-code-generator) |
| — server-side, for context — | | |
| Kafka broker | Apache-2.0 (server, not shipped) | Apache Kafka |
| Pulsar broker | Apache-2.0 (server, not shipped) | Apache Pulsar |
| RabbitMQ server | **MPL-2.0** (server, not shipped) | RabbitMQ |
| **Confluent Schema Registry (SERVER)** | **Confluent Community License — source-available, NOT OSI/permissive** | [GitHub confluentinc/schema-registry LICENSE](https://github.com/confluentinc/schema-registry/blob/master/LICENSE) · [Confluent Community License FAQ](https://www.confluent.io/confluent-community-license-faq/) |

---

## 2. AD-9 verdict per library

**AD-9-SAFE (permissive — bind freely):**
- `confluent-kafka` (Apache-2.0) + `librdkafka` (BSD-2-Clause) — both permissive. **Recommended Kafka client** (SC-2): it also ships the Apache-2.0 SchemaRegistryClient + Avro/JSON/Protobuf serializers, covering SC-3 and SC-4 wire-format in one dep.
- `kafka-python` (Apache-2.0), `aiokafka` (Apache-2.0) — safe pure-Python / async alternatives.
- `pulsar-client` (Apache-2.0) — safe for SC-8.
- `pika` (BSD-3-Clause), `aio-pika` (Apache-2.0) — both safe for SC-8 RabbitMQ.
- `fastavro` (MIT), `avro` (Apache-2.0), `protobuf` (BSD-3-Clause), `jsonschema` (MIT) — all safe for SC-3 serialization / SC-5 validation.
- `openapi-core` (BSD-3-Clause), `datamodel-code-generator` (MIT) — safe for SC-5 contract ingestion.

**AD-9 FLAG (not a Python dep, but a real constraint on the design):**
- **Confluent Schema Registry SERVER = Confluent Community License.** Source-available with a no-competing-SaaS restriction; it is **not** an OSI-permissive license and is **not** in the AD-9 allowlist. Impact:
  - *No impact* if TYMI only **depends on the Apache-2.0 client** and talks to a registry the user already runs (the normal case). SC-4 as written ("register/resolve against a schema registry") is fine.
  - *AD-9 violation* if PRD 3 ever bundles, redistributes, or auto-provisions a Confluent registry as part of TYMI (e.g. a "reference broker + registry" fixture shipped in the repo, or an SC-11-style "provision a streaming env" that stands one up). For that path use **Apicurio Registry (Apache-2.0)** or **AWS Glue Schema Registry**, both Confluent-wire-compatible. **Recommend OQ-4 resolve to "registry-agnostic client, Apicurio as the shippable reference."**
- RabbitMQ server is MPL-2.0 (file-level copyleft) — irrelevant since TYMI ships only the BSD/Apache client, but note it if any reference-env fixture bundles the broker.

**Net:** zero AD-9-risky *dependencies*. One AD-9 design rule: never ship/provision the Confluent registry server; keep the registry an external, user-supplied endpoint (or swap in Apicurio).

---

## 3. Feasibility risks

### R1 — "Byte-identical reproducibility into a partitioned Kafka topic" (SC / AD-4 / AD-11) — HIGH, needs scoping
Deterministic *ordering* is achievable; literal *byte-identical on-broker bytes* is not a contract TYMI can honor, and the PRD conflates the two.
- **What is achievable and should be the contract:** a deterministic *emitted sequence* (record order + partition assignment + payload bytes) for a given config+seed — which G1/G3 actually say ("identical emitted sequence"). TYMI controls this fully by ordering in its own emit layer before handing to the producer.
- **What is NOT controllable and must be excluded from the repro claim:** bytes as stored/observed on the broker. Kafka records carry a **CreateTime timestamp** (varies per run unless TYMI sets it explicitly), broker-assigned **offsets**, optional **compression** (codec framing can differ), and log-compaction state. Any of these breaks "byte-identical."
- **Ordering pitfalls to pin down:** the async producer batches and **retries can reorder** within a partition unless you enable the **idempotent producer** (`enable.idempotence=true`) or force `max.in.flight.requests.per.connection=1`. Partition choice must be **explicit** (don't rely on key-hash — murmur2 is deterministic but couples the sequence to the partition count). Serialization must be canonical (Avro canonical form / stable Protobuf field order / **sorted JSON keys**) or "same seed" won't produce same bytes.
- **Recommendation:** define the reproducibility SLA at TYMI's *emit boundary* (the sequence of `(partition, key, value-bytes)` tuples + the Fault Manifest), not the broker's on-disk state; set message timestamps deterministically from seed; require idempotent producer; canonicalize serialization. Add an OQ to lock this wording before Phase 1.

### R2 — Schema-registry integration (SC-4) — MODERATE, mostly a mapping problem not a protocol problem
The hard part (wire format: 5-byte magic + schema-id framing, register/resolve, compatibility checks) is **already implemented in the Apache-2.0 `confluent-kafka` serializers** — low lift if Confluent-compatible. The real work is **SC-3/CM2**: mapping TYMI's canonical Schema (AD-10) → an Avro/JSON-Schema/Protobuf schema document with **no silent field loss** (nullability, logical types, decimals, unions, nested records). That mapping is net-new and is where round-trip data-loss bugs will live. Registry-agnostic support (Apicurio/Glue) is extra adapter work — keep it behind the same port. Lift: moderate, front-loaded on the canonical-Schema→IDL mapping, not the network protocol.

### R3 — Contract-invalid payload generation (SC-7) — this is a NEW capability, not free on the mutator engine
The mutator engine (Story 3.1, pluggable Mutator) is the right *substrate* (pluggable mutators + Fault Manifest recording), but SC-7 needs a **new, contract-aware mutator family** that TYMI must build:
- The existing mutators perturb values/records blind. Contract-invalid generation must **read the contract's constraints** (JSON-Schema/OpenAPI keywords: `type`, `required`, `enum`, `minimum`/`maximum`, `pattern`, `format`, `additionalProperties`) and **deliberately violate one chosen constraint while keeping the rest valid** — that "surgical single-violation" behavior is what makes CM1's *subtle* violations (not just gross malformations) possible.
- No OSS library does this. `jsonschema` and `openapi-core` **validate only** — they do not generate instances, valid or invalid. `datamodel-code-generator` emits **code** (Pydantic models), not payload instances. So **SC-6 valid-payload generation** must be built on TYMI's own faithful generator + the SC-3 schema mapping, and **SC-7 invalid generation is entirely TYMI-built**. (A validator like `jsonschema` is still valuable as the *oracle* that confirms a "supposed-to-be-invalid" payload actually fails and a "valid" one passes — wire it into the acceptance test for G2/CM2.)
- Verdict: architecturally supported (pluggable mutator + manifest = good fit), but scope it as a **new schema-aware mutator family parameterized by contract constraints**, not a reuse of existing mutators. This is the differentiated wedge and also the largest net-new build in the PRD.

### R4 — minor: client/broker split is clean, but SC-11 "provision a streaming env" risks pulling in a server
SC-11 (faithful stream provisioning) and any "reference broker" test fixture are where an Apache-2.0-clean design can accidentally bundle a non-permissive server (Confluent registry, or MPL RabbitMQ). Keep provisioning to *client emit against a user-supplied endpoint*; if a self-contained reference env is wanted, assemble it from Apache-2.0 parts only (Kafka/Pulsar broker + Apicurio registry).

---

## Summary of verdicts

- **AD-9-safe (all client deps):** confluent-kafka, librdkafka, kafka-python, aiokafka, pulsar-client, pika, aio-pika, fastavro, avro, protobuf, jsonschema, confluent-kafka schema-registry client, openapi-core, datamodel-code-generator.
- **AD-9 flag:** Confluent Schema Registry **server** (Confluent Community License — source-available, not permissive) and RabbitMQ **server** (MPL-2.0). Fine to *talk to*, not fine to *ship/provision*. Use Apicurio (Apache-2.0) if a bundled registry is ever needed.
- **Top feasibility risks:** (R1) redefine reproducibility at the emit boundary — broker-byte-identical is not honorable; (R3) SC-7 invalid-payload generation is a new contract-aware mutator family, not a reuse; (R2) SC-4 lift is really the canonical-Schema→IDL mapping (data-loss risk), the wire protocol is already in the Apache-2.0 client.
