# TYMI — Fake It Till You Make It

> Generate synthetic data that is **statistically indistinguishable** from your real tables — or **deliberately broken** to stress-test your pipelines. No real data ever leaves the building.

**TYMI** is a Python tool for data teams who need realistic datasets without the privacy, compliance, and security risk of copying production data. It does two things, with equal weight:

1. **Faithful Generator** — learns the *statistical signature* of a real table (distributions, correlations, referential integrity) and produces fake rows that look statistically identical but contain **no real values**. Safe for dev, test, demos, and CI.
2. **Data Chaos Monkey** — deliberately produces **broken data** (out-of-distribution values, invalid formats/types, schema and constraint violations) in a **controlled, reproducible, and auditable** way, so you can test whether your pipelines and validations catch bad data *before* production does.

You drive it from a **CLI**, a **Python library**, or a **web UI** — all three do exactly the same thing because they read the same declarative config file.

## Documentation

Living docs live in [`docs/`](docs/): a single-page visual [overview](docs/overview.html)
of everything TYMI does, plus [how it works](docs/how-it-works.md),
[provisioning](docs/provisioning.md) (whole-DB obfuscated dev environments),
[development](docs/development.md), and [status](docs/status.md). They are kept
current as the project progresses.

## Why TYMI

- **Privacy by construction.** Faithful output is checked against the real values with an *exact membership check* — absence of leakage is proven, not estimated.
- **Statistically real, not just plausible.** Unlike random fixtures, TYMI preserves distributions and correlations, so the edge cases that break systems in production survive.
- **Robustness testing that doesn't exist elsewhere.** The Chaos Monkey systematically generates the malformed, out-of-distribution, and schema-breaking data most test suites never cover — with a full manifest of every fault it injected.
- **Any engine → any engine.** Profile from one database and load into another. MSSQL, StarRocks, PostgreSQL, and MySQL are first-class and interchangeable as source or destination.
- **Reproducible.** Same config + same seed ⇒ the same output, every time. Built for CI.

## How it works

```
Connect → Profile → Generate (Faithful | Chaos) → Privacy/Leakage Gate → Evaluate → Export
```

- **Connect & Profile** any supported engine; the Profile stores only aggregates (never raw values) and is reusable offline.
- **Generate** faithful data (in-house Gaussian copula for correlations + realistic synthetic values) or chaotic data (pluggable fault mutators driven by a declarative policy).
- **Leakage Gate** runs on *both* paths so no real sensitive value ever reaches the output.
- **Evaluate** produces a Fidelity Report and a Quality & Privacy Report (faithful) or validates the Fault Manifest (chaos).
- **Export** to CSV/Parquet/JSON, SQL `INSERT`, or a direct load into any engine.

The design is a clean **Ports & Adapters (hexagonal)** core: new database engines and new fault types are plug-ins discovered automatically, with no changes to the core.

## Key features

- Faithful synthetic data: marginal distributions, pairwise correlations, referential integrity, realistic formatted values, and conditional/seeded generation.
- Data Chaos Monkey: out-of-distribution, format/type, and schema/constraint faults, with a configurable rate/targeting policy and a seed-reproducible Fault Manifest.
- Automatic PII / sensitive-column classification, privacy filters, and measurable privacy metrics.
- CLI + Python library + Streamlit web UI, all driven by one versioned YAML config.

## Tech stack

Python 3.11+, CPU-only, and **every dependency is permissively licensed** so TYMI stays free to use and distribute in production. Core libraries: pandas / numpy / scipy, an in-house Gaussian copula, Faker, SDMetrics (quality & privacy metrics), Presidio (PII detection), SQLAlchemy with pyodbc / PyMySQL / psycopg, Pydantic, Typer (CLI), Streamlit (UI). Notably, SDV and Copulas are **excluded** because their BUSL-1.1 license restricts production use.

## Project status

🚧 **In development.** Product and technical planning are complete; implementation is beginning.

Planning artifacts (all in `_bmad-output/planning-artifacts/`):

- **PRD** — `prds/prd-tymi-2026-07-01/prd.md`
- **Architecture spine + solution design** — `architecture/architecture-tymi-2026-07-01/`
- **Epics & stories** — `epics.md`

### Roadmap

| Epic | Delivers |
| --- | --- |
| 1. Foundation & Source Profiling | Connect to any of the 4 engines and build a reusable, privacy-safe Profile |
| 2. Faithful Synthetic Data | Statistically faithful, exportable synthetic data + Fidelity Report |
| 3. Data Chaos Monkey | Controlled, auditable corrupted datasets + Fault Manifest |
| 4. Privacy & Evaluation | Auto PII classification, privacy filters, Quality & Privacy Report |
| 5. Web UI | Full workflow from the browser (Streamlit) |

## License

Intended to be released under a permissive open-source license (all dependencies are permissive). License file to be added.

---

*Product, architecture, and backlog were planned with the [BMAD Method](https://docs.bmad-method.org/).*
