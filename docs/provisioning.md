# Obfuscated Prod-Like Dev Environments (whole-DB provisioning)

> Post-MVP capability (PRD 1, Phase 1). Spin up a **whole**, realistic, FK-consistent,
> fully-obfuscated database in a non-prod environment — in minutes, self-service, from one
> command — without moving production data and without a Data Engineering ticket.

The MVP profiles and generates **one table at a time**. This capability lifts that to the **whole
database**, adds **cross-team consistency** (two teams get the *same* synthetic entities), lets you
**pin exact login/test accounts**, and puts a **fail-closed guardrail** in front of every write.

## The problem it solves

- Dev/test data doesn't reflect production's distribution and behaviour, so bugs hide until prod.
- Copying prod down to lower environments is a privacy/compliance risk and needs a Data Eng team.
- Different teams generate their datasets independently, so the *same* customer has a different id
  in each team's environment — joins across teams silently return garbage.

## The core idea: a Spec

A **`Spec`** is a single, versioned, editable YAML that describes a whole obfuscated database. You
**bootstrap** it once from a real source (introspect → sample → profile every table), then edit it
by hand. It bundles, per table:

- the **pinned Profile** (its FK graph, stats, and sensitive marks) — embedded, so regeneration
  reads the Spec **offline** and never re-profiles the source;
- the **row count** to generate;
- **shared-key** column declarations (cross-team join keys);
- a **reserved keyspace block** for fixtures;
- **pinned fixtures** (verbatim rows);

plus a global **seed**, a fidelity **tolerance**, and a **destination** block.

```yaml
schema_version: "1.0.0"
seed: 42
tolerance: 0.9
destination:
  environment: nonprod          # the affirmation the guardrail requires
  host: dev-db.internal
  database: app_dev
tables:
  customers:
    profile: { ... }            # the pinned Profile (bundled, offline)
    rows: 10000
    shared_keys: [customer_id]  # identical across teams
    reserved_key_block: 1000    # keys [0,1000) reserved for fixtures
    fixtures:
      - { customer_id: 1, email: "qa.admin@test.dev" }   # a pinned login account
```

## The consistency unit (why two teams match)

Reproducible identity is a **consistency unit**:

```
(Spec + the pinned Profile artifacts + seed + pinned dependency versions + the fixture set)
```

Two teams that share the same unit produce **byte-identical** data. Each run emits a
**consistency-unit fingerprint** (a hash over exactly those artifacts) — it only matches when the
unit truly matches, so a drifted/re-profiled source or a bumped dependency shows up as a *different
fingerprint* instead of silently mismatched entities.

## How the guarantees are built

| Guarantee | Mechanism |
| --- | --- |
| **Whole DB, FK-consistent** | `generate_from_spec` runs every table in FK-topological order (parents before children) via `generate_related`; an out-of-spec FK parent fails closed. |
| **Per-table RNG substreams** | Each table draws from a deterministic substream derived from `(seed, table_name)` — so a table's rows and FK edges are byte-identical regardless of an **unrelated** table's row count or the generation order. This is what keeps shared entities' relationships stable across teams. |
| **Source- & seed-independent shared keys** | A column declared `shared` is emitted position-derived — `key = reserved_key_block + position` — depending only on the table and row position, not the source values or the seed. Given the same pinned row counts, two teams get **identical** shared keys. Referencing FKs are remapped so integrity holds. |
| **Reserved fixture keyspace** | Fixtures occupy the low integer block `[0, reserved_key_block)`; generated keys are emitted at/above it — disjoint by construction, validated fail-closed. |
| **Pinned fixtures, no PII bypass** | Fixtures are injected **verbatim** and **never regenerated**, but the overlaid frame passes a **scan-and-reject** gate: every guarded column of the fixture rows is checked against the real-value set, and a PII classifier scans un-guarded columns. A real value or un-guarded PII **fails closed** — so a fixture can't become a privacy hole. Adding a fixture logs an attestation. |
| **Only gated data is written** | A table becomes a **`GatedDataset`** (a type that can only be minted by the leakage/scan gate). The provisioning `load` boundary accepts a `GatedDataset` and refuses a raw `Dataset` — un-gated data reaching a destination is a *type error*, not a matter of discipline. |
| **No accidental prod write** | Before any write, a guardrail requires the destination to affirm `environment: nonprod` **and** not match a configured prod deny-list (case-insensitive host/database globs, e.g. `*prod*`). A missing affirmation aborts; an empty deny-list never means "allow all". The CLI additionally cross-checks that the real `--config` connection matches the affirmed destination. |
| **Idempotent** | Each table is loaded with a clean-replace (`if_exists="replace"`), so a re-run overwrites rather than appends — a failed run self-heals on re-run. |

## The one command

```bash
tymi provision --spec dev-env.spec.yaml --engine postgres --config runner.yaml
```

Runs the one composition-adapter pipeline the CLI and any CI job / Airflow DAG call **identically**:

```
load Spec
  → guardrail (fail closed on a production destination)
  → per-table faithful generate (leakage gate embedded)
  → per-table RNG substreams
  → shared-key emission
  → fixtures overlay + scan-and-reject
  → GatedDataset
  → EngineAdapter.load (idempotent clean-replace)
  → provisioning report (with the consistency-unit fingerprint)
```

Orchestration (scheduling, retries) stays **external** — this pipeline runs once, in-process. It
prints a **provisioning report**: per table the row count, fixtures present, gated columns, and
fidelity, plus the consistency-unit fingerprint.

## Where it lives in the code

| Module | Responsibility |
| --- | --- |
| `config/spec.py` | The versioned `Spec` / `TableSpec` / `DestinationSpec` model + `bootstrap_from_source`. |
| `config/consistency.py` | The consistency-unit fingerprint. |
| `synth/whole_db.py` | `generate_from_spec` — the whole-DB pipeline (generate → shared keys → fixtures → seal). |
| `synth/substreams.py` | Per-table RNG substreams. |
| `synth/keys.py` | Position-derived shared keys + reserved-keyspace validation. |
| `synth/fixtures.py` | Fixtures overlay + FK/keyspace validation + attestation. |
| `synth/leakage.py` | `scan_and_gate` — the scan-and-reject seal (alongside the MVP gate). |
| `domain/artifacts.py` | The `GatedDataset` load-boundary type. |
| `provision/guardrail.py` | The non-prod destination guardrail. |
| `provision/pipeline.py` | `provision(spec, adapter)` — the composition-adapter pipeline + report. |
| `cli/app.py` | The `tymi provision` command. |

`tymi.provision` is a **driving/composition adapter**: it composes the synth + engine adapters and
is forbidden (by import-linter) from being imported by `core`/`ports`/`domain`.

## Scope & what's deferred

Phase 1 validates the cross-team-consistency wedge on the current **in-memory** engine at small
scale. Deferred:

- **Phase 2** — out-of-core rewrite for arbitrarily large databases (the per-table substreams are
  the seam the chunked/parallel design extends).
- **Phase 3** — cross-table statistical correlation, referentially-consistent subsetting, and
  incremental/delta refresh.
- **Whole-DB transactional atomicity** — today loads are per-table clean-replace (idempotent, a
  re-run self-heals); one transaction spanning all tables is out of Phase-1 scope.

See the planning artifacts under
`_bmad-output/planning-artifacts/architecture/architecture-tymi-pde1-phase1-2026-07-04/` (spine
`AD-13..21`) and the per-story records in `_bmad-output/implementation-artifacts/pde1-*.md`.
