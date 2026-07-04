"""Story 3.1: pluggable Mutator engine (discovery, order, RNG, manifest merge)."""

from __future__ import annotations

import pandas as pd
import pytest

from tymi.chaos.engine import apply_chaos, resolve_mutators
from tymi.core.errors import ChaosError
from tymi.core.rng import make_rng
from tymi.domain.artifacts import (
    Column,
    Dataset,
    FaultManifest,
    LogicalType,
    Schema,
    fault_manifest_to_json,
    merge_fault_manifests,
)
from tymi.ports import Mutator


def _dataset() -> Dataset:
    frame = pd.DataFrame({"x": [1, 2, 3]})
    return Dataset(frame=frame, schema=Schema(columns=(Column("x", LogicalType.INTEGER),)))


class _DrawMutator:
    """Records the next rng draw so tests can observe order + RNG threading."""

    name = "draw"

    def apply(self, dataset: Dataset, *, rng) -> tuple[Dataset, FaultManifest]:
        draw = int(rng.integers(0, 1_000_000))
        return dataset, FaultManifest(entries=[{"mutator": self.name, "draw": draw}])


class _MutatorA(_DrawMutator):
    name = "a"


class _MutatorB(_DrawMutator):
    name = "b"


class _AddColumnMutator:
    """Mutates the Dataset itself so the chain-threading can be observed."""

    name = "add_col"

    def apply(self, dataset: Dataset, *, rng) -> tuple[Dataset, FaultManifest]:
        frame = dataset.frame.copy()
        frame["injected"] = 0
        return Dataset(frame=frame, schema=dataset.schema), FaultManifest(
            entries=[{"mutator": self.name, "column": "injected"}]
        )


_REGISTRY = {"a": _MutatorA, "b": _MutatorB, "add_col": _AddColumnMutator}


# --- resolution + discovery (AC-1, AC-2, AC-5) ------------------------------


def test_resolve_preserves_declared_order() -> None:
    resolved = resolve_mutators(["b", "a"], registry=_REGISTRY)
    assert [m.name for m in resolved] == ["b", "a"]
    assert all(isinstance(m, Mutator) for m in resolved)


def test_resolve_unknown_name_raises_chaos_error() -> None:
    with pytest.raises(ChaosError, match="unknown mutator 'nope'"):
        resolve_mutators(["nope"], registry=_REGISTRY)


def test_resolve_non_mutator_raises_chaos_error() -> None:
    class _NotAMutator:
        pass

    with pytest.raises(ChaosError, match="does not satisfy the Mutator port"):
        resolve_mutators(["bad"], registry={"bad": _NotAMutator})


def test_discovery_uses_entry_point_registry(monkeypatch) -> None:
    # resolve_mutators with no explicit registry pulls from load_mutators (AD-3).
    monkeypatch.setattr("tymi.chaos.engine.load_mutators", lambda: {"a": _MutatorA})
    resolved = resolve_mutators(["a"])
    assert [m.name for m in resolved] == ["a"]


def test_new_mutator_runs_with_zero_engine_changes() -> None:
    # a Mutator the engine has never heard of runs purely by being in the registry.
    class _BrandNew:
        name = "brand_new"

        def apply(self, dataset, *, rng):
            return dataset, FaultManifest(entries=[{"mutator": "brand_new"}])

    mutators = resolve_mutators(["brand_new"], registry={"brand_new": _BrandNew})
    _, manifest = apply_chaos(_dataset(), mutators, rng=make_rng(0))
    assert manifest.entries == [{"mutator": "brand_new"}]


# --- running the chain (AC-3, AC-4, AC-6) -----------------------------------


def test_apply_runs_in_order_and_merges_manifests() -> None:
    mutators = resolve_mutators(["a", "b"], registry=_REGISTRY)
    _, manifest = apply_chaos(_dataset(), mutators, rng=make_rng(7))
    assert [e["mutator"] for e in manifest.entries] == ["a", "b"]  # merged, in order


def test_shared_rng_is_threaded_not_recreated() -> None:
    # a shared, advancing generator → the two mutators draw *different* values; a fresh
    # per-mutator rng would make them identical.
    mutators = resolve_mutators(["a", "b"], registry=_REGISTRY)
    _, manifest = apply_chaos(_dataset(), mutators, rng=make_rng(7))
    assert manifest.entries[0]["draw"] != manifest.entries[1]["draw"]


def test_deterministic_same_seed() -> None:
    mutators = resolve_mutators(["a", "b"], registry=_REGISTRY)
    _, m1 = apply_chaos(_dataset(), mutators, rng=make_rng(7))
    _, m2 = apply_chaos(_dataset(), mutators, rng=make_rng(7))
    assert m1.entries == m2.entries


def test_dataset_is_threaded_through_the_chain() -> None:
    # add_col mutates the Dataset; a following mutator + the final result see the change.
    mutators = resolve_mutators(["add_col", "a"], registry=_REGISTRY)
    result, _ = apply_chaos(_dataset(), mutators, rng=make_rng(0))
    assert "injected" in result.frame.columns


def test_empty_chain_is_a_no_op() -> None:
    ds = _dataset()
    result, manifest = apply_chaos(ds, [], rng=make_rng(0))
    assert result is ds and manifest.entries == []


def test_merged_manifest_reflects_declared_order_when_reversed() -> None:
    # AC-2: the order must be observable in the manifest for a NON-alphabetical chain.
    mutators = resolve_mutators(["b", "a"], registry=_REGISTRY)
    _, manifest = apply_chaos(_dataset(), mutators, rng=make_rng(1))
    assert [e["mutator"] for e in manifest.entries] == ["b", "a"]


def test_following_mutator_sees_previous_mutation() -> None:
    seen: dict[str, bool] = {}

    class _Observer:
        name = "observer"

        def apply(self, dataset, *, rng):
            seen["injected"] = "injected" in dataset.frame.columns
            return dataset, FaultManifest()

    mutators = resolve_mutators(
        ["add_col", "observer"], registry={**_REGISTRY, "observer": _Observer}
    )
    apply_chaos(_dataset(), mutators, rng=make_rng(0))
    assert seen["injected"] is True  # the second mutator received the first's change


def test_schema_is_preserved_when_no_mutator_touches_it() -> None:
    ds = _dataset()
    result, _ = apply_chaos(ds, resolve_mutators(["a", "b"], registry=_REGISTRY), rng=make_rng(0))
    assert result.schema == ds.schema  # AD-10


# --- robustness: malformed / misbehaving mutators ---------------------------


class _BadReturnMutator:
    name = "bad_return"

    def apply(self, dataset, *, rng):
        return dataset  # not a (Dataset, FaultManifest) pair


class _NoneDatasetMutator:
    name = "none_ds"

    def apply(self, dataset, *, rng):
        return None, FaultManifest()  # dataset slot is None


def test_malformed_return_raises_chaos_error() -> None:
    mutators = resolve_mutators(["bad_return"], registry={"bad_return": _BadReturnMutator})
    with pytest.raises(ChaosError, match="must return a .Dataset, FaultManifest. pair"):
        apply_chaos(_dataset(), mutators, rng=make_rng(0))


def test_none_dataset_return_raises_chaos_error() -> None:
    mutators = resolve_mutators(["none_ds"], registry={"none_ds": _NoneDatasetMutator})
    with pytest.raises(ChaosError, match="expected .Dataset, FaultManifest."):
        apply_chaos(_dataset(), mutators, rng=make_rng(0))


def test_registry_instance_raises_chaos_error() -> None:
    # a registry value that is already an instance (not a class/factory) is not callable.
    with pytest.raises(ChaosError, match="could not be instantiated"):
        resolve_mutators(["inst"], registry={"inst": _MutatorA()})


def test_factory_raising_on_init_raises_chaos_error() -> None:
    class _Boom:
        def __init__(self) -> None:
            raise RuntimeError("boom")

    with pytest.raises(ChaosError, match="could not be instantiated"):
        resolve_mutators(["boom"], registry={"boom": _Boom})


def test_in_place_mutation_does_not_leak_to_caller() -> None:
    class _InPlace:
        name = "in_place"

        def apply(self, dataset, *, rng):
            dataset.frame["x"] = dataset.frame["x"] * 100  # mutates in place (contract violation)
            return dataset, FaultManifest(entries=[{"mutator": self.name, "fault_type": "scale"}])

    ds = _dataset()
    original = ds.frame["x"].tolist()
    mutators = resolve_mutators(["in_place"], registry={"in_place": _InPlace})
    apply_chaos(ds, mutators, rng=make_rng(0))
    assert ds.frame["x"].tolist() == original  # the caller's dataset is untouched


# --- manifest helpers -------------------------------------------------------


def test_merge_fault_manifests_preserves_order() -> None:
    a = FaultManifest(entries=[{"i": 1}, {"i": 2}])
    b = FaultManifest(entries=[{"i": 3}])
    assert merge_fault_manifests([a, b]).entries == [{"i": 1}, {"i": 2}, {"i": 3}]


def test_fault_manifest_to_json_round_trips() -> None:
    import json

    manifest = FaultManifest(entries=[{"mutator": "a", "row": 0, "column": "x"}])
    data = json.loads(fault_manifest_to_json(manifest))
    assert data["entries"][0] == {"mutator": "a", "row": 0, "column": "x"}


def test_chaos_config_accepts_ordered_mutators() -> None:
    from tymi.config.models import ChaosConfig

    cfg = ChaosConfig(mutators=["a", "b"])
    assert cfg.mutators == ["a", "b"]
