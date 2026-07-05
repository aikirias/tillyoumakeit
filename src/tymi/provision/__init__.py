"""Provisioning — a driving/composition adapter (AD-19).

``tymi.provision`` exposes the one whole-DB provisioning pipeline the CLI command and any external
DAG/CI job call identically. It composes the synth + engine adapters; the core/ports/domain never
import it (import-linter enforces this). Orchestration (scheduling, retries) stays external.
"""
