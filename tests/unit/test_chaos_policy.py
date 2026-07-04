"""Story 3.5: configurable Chaos Policy (mixed / fully-chaotic) + resolution."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tymi.chaos.policy import apply_policy, resolve_policy
from tymi.config.models import ChaosConfig, MutatorSpec
from tymi.core.errors import ChaosError
from tymi.core.rng import make_rng
from tymi.domain.artifacts import Column, Dataset, ForeignKey, LogicalType, Schema
from tymi.ports import Mutator


def _dataset(n: int = 1000, *, with_fk: bool = False) -> Dataset:
    rng = np.random.default_rng(0)
    frame = pd.DataFrame(
        {
            "age": pd.array(rng.integers(20, 70, n), dtype="Int64"),
            "score": rng.normal(0.0, 1.0, n),
        }
    )
    columns = (Column("age", LogicalType.INTEGER), Column("score", LogicalType.FLOAT))
    fks = (
        (ForeignKey(columns=("age",), referred_table="p", referred_columns=("id",)),)
        if with_fk
        else ()
    )
    return Dataset(frame=frame, schema=Schema(columns=columns, foreign_keys=fks))


def _corrupted_fraction(dataset: Dataset, manifest) -> float:
    return len({e["row"] for e in manifest.entries if "row" in e}) / len(dataset.frame)


# --- resolution (AD-3/AD-5) -------------------------------------------------


def test_resolve_policy_builds_mutators_with_params() -> None:
    specs = [MutatorSpec(name="outlier", params={"columns": ["score"], "magnitude": 5.0})]
    mutators = resolve_policy(specs)
    assert len(mutators) == 1 and isinstance(mutators[0], Mutator)
    assert mutators[0].params.magnitude == 5.0 and mutators[0].params.columns == ["score"]


def test_resolve_policy_unknown_mutator_raises() -> None:
    with pytest.raises(ChaosError, match="unknown mutator 'nope'"):
        resolve_policy([MutatorSpec(name="nope")])


def test_resolve_policy_invalid_params_raise_chaos_error() -> None:
    with pytest.raises(ChaosError, match="invalid params for mutator 'outlier'"):
        resolve_policy([MutatorSpec(name="outlier", params={"magnitude": -1})])


# --- mixed mode (AC: fraction of corrupted rows ~ rate) ---------------------


@pytest.mark.parametrize("rate", [0.05, 0.1, 0.25])
def test_mixed_mode_corrupts_rate_fraction_within_margin(rate: float) -> None:
    ds = _dataset(2000)
    cfg = ChaosConfig(mode="mixed", rate=rate, mutators=[MutatorSpec(name="outlier")])
    out, manifest = apply_policy(ds, cfg, rng=make_rng(1))
    assert abs(_corrupted_fraction(out, manifest) - rate) <= 0.02  # ±2pp margin


def test_mixed_mode_hits_rate_even_with_nulls_in_target() -> None:
    # regression (HIGH): selecting from the actually-corrupted rows keeps the realised
    # fraction on target even when the targeted column is ~50% null.
    rng = np.random.default_rng(0)
    n = 2000
    age = pd.array(rng.integers(20, 70, n), dtype="Int64")
    age[rng.random(n) < 0.5] = pd.NA
    ds = Dataset(
        frame=pd.DataFrame({"age": age}),
        schema=Schema(columns=(Column("age", LogicalType.INTEGER),)),
    )
    cfg = ChaosConfig(
        mode="mixed",
        rate=0.1,
        mutators=[MutatorSpec(name="text_in_numeric", params={"columns": ["age"]})],
    )
    out, manifest = apply_policy(ds, cfg, rng=make_rng(1))
    assert abs(_corrupted_fraction(out, manifest) - 0.1) <= 0.02


def test_mixed_mode_preserves_numeric_dtype_of_touched_column() -> None:
    # regression (MEDIUM): a numeric fault (outlier) must not force the column to object.
    ds = _dataset(1000)
    spec = MutatorSpec(name="outlier", params={"columns": ["score"]})
    cfg = ChaosConfig(mode="mixed", rate=0.1, mutators=[spec])
    out, _ = apply_policy(ds, cfg, rng=make_rng(1))
    assert out.frame["score"].dtype == "float64"


def test_policy_overrides_per_mutator_proportion() -> None:
    # the policy's rate governs density; a MutatorSpec proportion is superseded by 1.0.
    mutators = resolve_policy(
        [MutatorSpec(name="outlier", params={"proportion": 0.1})], proportion=1.0
    )
    assert mutators[0].params.proportion == 1.0


def test_mixed_mode_leaves_other_rows_faithful() -> None:
    ds = _dataset(1000)
    cfg = ChaosConfig(mode="mixed", rate=0.1, mutators=[MutatorSpec(name="outlier")])
    out, manifest = apply_policy(ds, cfg, rng=make_rng(1))
    corrupted = {e["row"] for e in manifest.entries}
    faithful = [i for i in range(len(ds.frame)) if i not in corrupted]
    # untouched rows are identical to the source
    for col in ds.frame.columns:
        got = out.frame[col].iloc[faithful].to_numpy()
        want = ds.frame[col].iloc[faithful].to_numpy()
        assert (got == want).all()


def test_mixed_mode_rejects_structural_mutators() -> None:
    ds = _dataset(100)
    cfg = ChaosConfig(mode="mixed", rate=0.2, mutators=[MutatorSpec(name="missing_field")])
    with pytest.raises(ChaosError, match="structural mutators .* cannot run in mixed mode"):
        apply_policy(ds, cfg, rng=make_rng(1))


def test_mixed_mode_deterministic() -> None:
    ds = _dataset(500)
    cfg = ChaosConfig(mode="mixed", rate=0.1, mutators=[MutatorSpec(name="outlier")])
    a_ds, a_man = apply_policy(ds, cfg, rng=make_rng(3))
    b_ds, b_man = apply_policy(ds, cfg, rng=make_rng(3))
    assert a_man.entries == b_man.entries
    pd.testing.assert_frame_equal(a_ds.frame, b_ds.frame)


# --- fully-chaotic mode + FK confirmation -----------------------------------


def test_fully_chaotic_over_fk_table_requires_confirmation() -> None:
    ds = _dataset(200, with_fk=True)
    cfg = ChaosConfig(mode="fully_chaotic", mutators=[MutatorSpec(name="outlier")])
    with pytest.raises(ChaosError, match="referential integrity"):
        apply_policy(ds, cfg, rng=make_rng(1))
    # confirmed → runs
    out, manifest = apply_policy(ds, cfg, rng=make_rng(1), confirmed=True)
    assert manifest.entries


def test_fully_chaotic_without_fk_needs_no_confirmation() -> None:
    ds = _dataset(200, with_fk=False)
    cfg = ChaosConfig(mode="fully_chaotic", mutators=[MutatorSpec(name="outlier")])
    out, manifest = apply_policy(ds, cfg, rng=make_rng(1))  # no confirm needed
    assert manifest.entries


def test_fully_chaotic_allows_structural_mutators() -> None:
    ds = _dataset(200, with_fk=False)
    cfg = ChaosConfig(mode="fully_chaotic", mutators=[MutatorSpec(name="missing_field")])
    out, manifest = apply_policy(ds, cfg, rng=make_rng(1))
    assert manifest.entries and "age" not in out.frame.columns


def test_config_mode_is_validated() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ChaosConfig(mode="bananas")


# --- CLI ---------------------------------------------------------------------


def _saved_profile(tmp_path):
    from tymi.profiling.profile_io import save_profile
    from tymi.profiling.profiler import profile_dataset

    path = tmp_path / "p.yaml"
    save_profile(profile_dataset(_dataset(300)), path)
    return path


def _chaos_config(tmp_path, body: str):
    path = tmp_path / "c.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_cli_chaos_mixed_writes_data_and_manifest(tmp_path) -> None:
    from typer.testing import CliRunner

    from tymi.cli.app import app

    profile = _saved_profile(tmp_path)
    cfg = _chaos_config(
        tmp_path,
        "schema_version: '1.0.0'\nchaos:\n  mode: mixed\n  rate: 0.1\n  mutators:\n"
        "    - name: outlier\n",
    )
    manifest = tmp_path / "m.json"
    result = CliRunner().invoke(
        app,
        ["chaos", "-p", str(profile), "-c", str(cfg), "-n", "500", "--manifest", str(manifest)],
    )
    assert result.exit_code == 0, result.stdout
    assert manifest.exists()
    import json

    assert json.loads(manifest.read_text())["entries"]


def test_cli_chaos_fully_chaotic_fk_needs_confirm(tmp_path) -> None:
    from typer.testing import CliRunner

    from tymi.cli.app import app
    from tymi.profiling.profile_io import save_profile
    from tymi.profiling.profiler import profile_dataset

    profile = tmp_path / "p.yaml"
    save_profile(profile_dataset(_dataset(200, with_fk=True)), profile)
    cfg = _chaos_config(
        tmp_path,
        "schema_version: '1.0.0'\nchaos:\n  mode: fully_chaotic\n"
        "  mutators:\n    - name: outlier\n",
    )
    result = CliRunner().invoke(app, ["chaos", "-p", str(profile), "-c", str(cfg), "-n", "200"])
    assert result.exit_code == 1
    assert "referential integrity" in result.stdout
    ok = CliRunner().invoke(
        app, ["chaos", "-p", str(profile), "-c", str(cfg), "-n", "200", "--confirm"]
    )
    assert ok.exit_code == 0
