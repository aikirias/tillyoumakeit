"""Story 3.6: bidirectional Fault Manifest audit + Evaluate chaos run_mode."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tymi.chaos.policy import apply_policy
from tymi.config.models import ChaosConfig, MutatorSpec
from tymi.core.rng import make_rng
from tymi.domain.artifacts import (
    Column,
    Dataset,
    FaultManifest,
    LogicalType,
    ManifestAudit,
    Schema,
    manifest_audit_to_json,
)
from tymi.eval.chaos_audit import audit_manifest
from tymi.eval.evaluate import evaluate, is_manifest_audit


def _dataset(n: int = 400) -> Dataset:
    rng = np.random.default_rng(0)
    frame = pd.DataFrame(
        {
            "id": pd.array(range(n), dtype="Int64"),
            "age": pd.array(rng.integers(20, 70, n), dtype="Int64"),
            "score": rng.normal(0.0, 1.0, n),
        }
    )
    schema = Schema(
        columns=(
            Column("id", LogicalType.INTEGER, primary_key=True),
            Column("age", LogicalType.INTEGER),
            Column("score", LogicalType.FLOAT),
        ),
        primary_key=("id",),
    )
    return Dataset(frame=frame, schema=schema)


def _drop_col(schema: Schema, name: str) -> Schema:
    from dataclasses import replace

    return replace(
        schema,
        columns=tuple(c for c in schema.columns if c.name != name),
        primary_key=tuple(k for k in schema.primary_key if k != name),
    )


def _run(mode: str, mutators: list[str], **kw):
    ds = _dataset()
    cfg = ChaosConfig(mode=mode, mutators=[MutatorSpec(name=m) for m in mutators], **kw)
    chaotic, manifest = apply_policy(ds, cfg, rng=make_rng(1), confirmed=True)
    return ds, chaotic, manifest


# --- bidirectional contract (AC-1) ------------------------------------------


def test_clean_run_audits_valid_cell_faults() -> None:
    ds, chaotic, manifest = _run("mixed", ["outlier"], rate=0.2)
    audit = audit_manifest(ds, chaotic, manifest)
    assert audit.valid and not audit.listed_not_present and not audit.present_not_listed
    assert audit.checked == len(manifest.entries)


def test_present_fault_not_listed_is_caught() -> None:
    # backward direction: drop entries from the manifest → the changes are unlisted.
    ds, chaotic, manifest = _run("mixed", ["outlier"], rate=0.2)
    tampered = FaultManifest(entries=manifest.entries[:-5])
    audit = audit_manifest(ds, chaotic, tampered)
    assert not audit.valid and len(audit.present_not_listed) == 5


def test_listed_fault_not_present_is_caught() -> None:
    # forward direction: a phantom entry for an unchanged cell.
    ds, chaotic, manifest = _run("mixed", ["outlier"], rate=0.2)
    phantom = {
        "mutator": "x",
        "fault_type": "numeric_outlier",
        "row": 0,
        "column": "age",
        "value": "?",
    }
    tampered = FaultManifest(entries=[*manifest.entries, phantom])
    audit = audit_manifest(ds, chaotic, tampered)
    assert not audit.valid and any("row 0" in m for m in audit.listed_not_present)


def test_structural_faults_audit_valid() -> None:
    for mutator in ["missing_field", "renamed_column", "extra_field", "changed_type"]:
        ds, chaotic, manifest = _run("fully_chaotic", [mutator])
        audit = audit_manifest(ds, chaotic, manifest)
        assert audit.valid, f"{mutator}: {audit.present_not_listed} {audit.listed_not_present}"


def test_unlisted_column_drop_is_present_not_listed() -> None:
    # a real drop with no fault listed is a PRESENT change (right direction).
    ds = _dataset()
    chaotic = Dataset(frame=ds.frame.drop(columns=["age"]), schema=_drop_col(ds.schema, "age"))
    audit = audit_manifest(ds, chaotic, FaultManifest(entries=[]))
    assert not audit.valid
    assert any("removed" in m for m in audit.present_not_listed)


def test_unlisted_type_change_is_present_not_listed() -> None:
    ds = _dataset()
    cols = tuple(
        Column(c.name, LogicalType.STRING if c.name == "age" else c.logical_type)
        for c in ds.schema.columns
    )
    schema = Schema(columns=cols, primary_key=ds.schema.primary_key)
    chaotic = Dataset(frame=ds.frame, schema=schema)
    audit = audit_manifest(ds, chaotic, FaultManifest(entries=[]))
    assert not audit.valid and any("type changed" in m for m in audit.present_not_listed)


def test_duplicate_keys_on_repeating_column_audits_valid() -> None:
    # regression (HIGH): copying an existing value (composite key col that repeats) must
    # not false-fail — the fault materialised even when the cell value was unchanged.
    schema = Schema(
        columns=(Column("a", LogicalType.INTEGER), Column("b", LogicalType.INTEGER)),
        primary_key=("a", "b"),
    )
    from tymi.chaos.mutators.schema_break import DuplicateKeysMutator

    for seed in range(20):
        ds = Dataset(
            frame=pd.DataFrame(
                {
                    "a": pd.array([1, 1, 2] * 4, dtype="Int64"),
                    "b": pd.array(range(12), dtype="Int64"),
                }
            ),
            schema=schema,
        )
        chaotic, manifest = DuplicateKeysMutator(proportion=0.5).apply(ds, rng=make_rng(seed))
        assert audit_manifest(ds, chaotic, manifest).valid, f"seed {seed}"


@pytest.mark.parametrize(
    "specs",
    [
        [  # rename age, then corrupt the renamed column
            MutatorSpec(name="renamed_column", params={"columns": ["age"]}),
            MutatorSpec(name="outlier", params={"columns": ["age__renamed"]}),
        ],
        [  # corrupt age, then drop it
            MutatorSpec(name="outlier", params={"columns": ["age"]}),
            MutatorSpec(name="missing_field", params={"columns": ["age"]}),
        ],
    ],
)
def test_combined_structural_and_cell_chain_audits_valid(specs) -> None:
    # regression (HIGH): the cell diff cannot follow a structural change, so a value
    # fault on a renamed/dropped column is excused (structural check covers the column).
    ds = _dataset()
    cfg = ChaosConfig(mode="fully_chaotic", mutators=specs)
    chaotic, manifest = apply_policy(ds, cfg, rng=make_rng(1), confirmed=True)
    assert audit_manifest(ds, chaotic, manifest).valid


def test_non_integer_row_is_reported_not_crashed() -> None:
    ds = _dataset()
    manifest = FaultManifest(entries=[{"fault_type": "outlier", "row": "x", "column": "age"}])
    audit = audit_manifest(ds, ds, manifest)
    assert not audit.valid and any("non-integer row" in m for m in audit.listed_not_present)


def test_illegal_null_reads_as_a_change() -> None:
    # a value → null is a genuine cell change the audit must see (null-aware equality).
    ds = _dataset()
    cfg = ChaosConfig(mode="mixed", rate=0.2, mutators=[MutatorSpec(name="illegal_null")])
    # illegal_null defaults to non-nullable columns; make 'id' explicitly targeted
    cfg = ChaosConfig(
        mode="mixed",
        rate=0.2,
        mutators=[MutatorSpec(name="illegal_null", params={"columns": ["id"]})],
    )
    chaotic, manifest = apply_policy(ds, cfg, rng=make_rng(1))
    assert audit_manifest(ds, chaotic, manifest).valid


# --- determinism (AC-3) -----------------------------------------------------


def test_same_seed_same_manifest() -> None:
    _, _, a = _run("mixed", ["outlier"], rate=0.1)
    _, _, b = _run("mixed", ["outlier"], rate=0.1)
    assert a.entries == b.entries


# --- Evaluate dispatch (AC-4) -----------------------------------------------


def test_evaluate_chaos_returns_audit() -> None:
    ds, chaotic, manifest = _run("mixed", ["outlier"], rate=0.1)
    result = evaluate(chaotic, run_mode="chaos", baseline=ds, manifest=manifest)
    assert is_manifest_audit(result) and result.valid


def test_evaluate_faithful_returns_fidelity_not_audit() -> None:
    from tymi.profiling.profiler import profile_dataset
    from tymi.synth.generator import generate_faithful

    profile = profile_dataset(_dataset())
    gen = generate_faithful(profile, rows=300, rng=make_rng(1))
    result = evaluate(gen, run_mode="faithful", profile=profile, tolerance=0.7)
    assert not is_manifest_audit(result)  # a FidelityReport, not an audit
    assert hasattr(result, "per_column")


def test_evaluate_requires_mode_inputs() -> None:
    ds = _dataset()
    with pytest.raises(ValueError, match="chaos run_mode requires"):
        evaluate(ds, run_mode="chaos")
    with pytest.raises(ValueError, match="faithful run_mode requires"):
        evaluate(ds, run_mode="faithful")
    with pytest.raises(ValueError, match="unknown run_mode"):
        evaluate(ds, run_mode="bananas")


def test_audit_json_is_exportable() -> None:
    import json

    audit = ManifestAudit(valid=False, present_not_listed=("row 1 column 'x'",), checked=3)
    data = json.loads(manifest_audit_to_json(audit))
    assert data["valid"] is False and data["present_not_listed"] == ["row 1 column 'x'"]


# --- CLI (AC-5) -------------------------------------------------------------


def test_cli_chaos_audit_passes(tmp_path) -> None:
    from typer.testing import CliRunner

    from tymi.cli.app import app
    from tymi.profiling.profile_io import save_profile
    from tymi.profiling.profiler import profile_dataset

    profile = tmp_path / "p.yaml"
    save_profile(profile_dataset(_dataset()), profile)
    cfg = tmp_path / "c.yaml"
    cfg.write_text(
        "schema_version: '1.0.0'\nchaos:\n  mode: mixed\n  rate: 0.1\n  mutators:\n"
        "    - name: outlier\n",
        encoding="utf-8",
    )
    result = CliRunner().invoke(
        app, ["chaos", "-p", str(profile), "-c", str(cfg), "-n", "300", "--audit"]
    )
    assert result.exit_code == 0


def test_cli_chaos_audit_invalid_exits_1(tmp_path, monkeypatch) -> None:
    from typer.testing import CliRunner

    from tymi.cli import app as app_module
    from tymi.profiling.profile_io import save_profile
    from tymi.profiling.profiler import profile_dataset

    profile = tmp_path / "p.yaml"
    save_profile(profile_dataset(_dataset()), profile)
    cfg = tmp_path / "c.yaml"
    cfg.write_text(
        "schema_version: '1.0.0'\nchaos:\n  mode: mixed\n  rate: 0.1\n  mutators:\n"
        "    - name: outlier\n",
        encoding="utf-8",
    )
    # force an invalid audit → the CLI must exit 1 (the wired failure path)
    monkeypatch.setattr(
        app_module,
        "audit_manifest",
        lambda *a, **k: ManifestAudit(valid=False, present_not_listed=("x",)),
    )
    result = CliRunner().invoke(
        app_module.app, ["chaos", "-p", str(profile), "-c", str(cfg), "-n", "300", "--audit"]
    )
    assert result.exit_code == 1
