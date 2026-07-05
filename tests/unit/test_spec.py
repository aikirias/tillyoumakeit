"""PRD 1 Story 1.2: whole-DB Spec model + auto-bootstrap (AD-14)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tymi.config.spec import (
    Spec,
    bootstrap_from_source,
    bootstrap_spec,
    load_spec,
    save_spec,
    spec_profiles,
)
from tymi.core.errors import ConfigError, ConfigVersionError
from tymi.domain.artifacts import Column, Dataset, LogicalType, Schema, profile_to_json
from tymi.profiling.profiler import profile_dataset

_SCHEMA = Schema(
    columns=(
        Column("id", LogicalType.INTEGER),
        Column("score", LogicalType.FLOAT),
        Column("email", LogicalType.STRING),
    )
)


def _frame(n: int = 100) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    return pd.DataFrame(
        {
            "id": range(n),
            "score": rng.normal(0, 1, n),
            "email": [f"user{i}@x.com" for i in range(n)],
        }
    )


def _profile(sensitive=("email",)):
    return profile_dataset(
        Dataset(frame=_frame(), schema=_SCHEMA), sensitive_columns=list(sensitive), salt="s"
    )


class _FakeAdapter:
    supports_introspect = True
    supports_sample = True
    supports_write = True

    def __init__(self, connection=None) -> None:
        self.connection = connection

    def sample(self, table: str, *, rows: int, rng) -> Dataset:
        return Dataset(frame=_frame(), schema=_SCHEMA)


# --- bootstrap + bundling (AC-1) --------------------------------------------


def test_bootstrap_spec_bundles_profiles_and_sensitive() -> None:
    spec = bootstrap_spec({"customers": _profile()}, seed=7, tolerance=0.8)
    assert spec.seed == 7 and spec.tolerance == 0.8
    assert set(spec.tables) == {"customers"}
    ts = spec.tables["customers"]
    assert ts.sensitive_columns == ["email"]  # read from the Profile's leakage guard
    assert ts.fixtures == [] and ts.shared_keys == []  # placeholders for later stories


def test_bootstrap_from_source_via_fake_adapter() -> None:
    spec = bootstrap_from_source(
        _FakeAdapter(),
        ["customers", "orders"],
        rows=50,
        seed=1,
        sensitive_columns={"customers": ["email"]},
    )
    assert set(spec.tables) == {"customers", "orders"}
    assert spec.tables["customers"].sensitive_columns == ["email"]


# --- pinned Profiles + YAML round-trip (AC-2, AC-3) -------------------------


def test_spec_round_trips_through_yaml_preserving_profiles(tmp_path) -> None:
    from tymi.domain.artifacts import ForeignKey

    # An FK-bearing schema: the FK graph lives in the Profile and must survive the round-trip.
    schema = Schema(
        columns=(Column("id", LogicalType.INTEGER), Column("parent_id", LogicalType.INTEGER)),
        foreign_keys=(ForeignKey(("parent_id",), "parents", ("id",)),),
    )
    original = profile_dataset(
        Dataset(frame=pd.DataFrame({"id": range(50), "parent_id": range(50)}), schema=schema),
        salt="s",
    )
    spec = bootstrap_spec({"customers": original}, seed=3, tolerance=0.75)
    path = tmp_path / "spec.yaml"
    save_spec(spec, path)
    loaded = load_spec(path)
    # Spec scalars round-trip
    assert loaded.seed == 3 and loaded.tolerance == 0.75
    # the reconstructed Profile equals the pinned original (bundled, not a live reference),
    # FK graph included
    reconstructed = spec_profiles(loaded)["customers"]
    assert profile_to_json(reconstructed) == profile_to_json(original)
    assert reconstructed.schema.foreign_keys[0].referred_table == "parents"


def test_bootstrap_from_source_is_reproducible_for_a_seed() -> None:
    # salt=None derives the salt from the seed, so the same source+seed yields an identical
    # Spec (AD-15 offline reproducibility) — including identical leakage-guard digests.
    a = bootstrap_from_source(_FakeAdapter(), ["t"], seed=5, sensitive_columns={"t": ["email"]})
    b = bootstrap_from_source(_FakeAdapter(), ["t"], seed=5, sensitive_columns={"t": ["email"]})
    assert a.model_dump() == b.model_dump()


def test_save_spec_wraps_write_error() -> None:
    with pytest.raises(ConfigError, match="Could not write spec file"):
        save_spec(bootstrap_spec({}), "/no_such_dir_xyz/spec.yaml")


def test_spec_rejects_unknown_keys() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Spec.model_validate({"schema_version": "1.0.0", "tables": {}, "bogus": 1})


def test_load_spec_rejects_unknown_major(tmp_path) -> None:
    import yaml

    path = tmp_path / "spec.yaml"
    path.write_text(yaml.safe_dump({"schema_version": "2.0.0", "tables": {}}), encoding="utf-8")
    with pytest.raises(ConfigVersionError):
        load_spec(path)


def test_load_spec_rejects_malformed(tmp_path) -> None:
    path = tmp_path / "spec.yaml"
    path.write_text("- not\n- a mapping\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_spec(path)


def test_tolerance_bounds() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Spec(tolerance=1.5)
    with pytest.raises(ValidationError):
        Spec(tolerance=-0.1)
