"""PRD 1 Story 2.3: consistency unit + fingerprint (AD-15, PDE-11)."""

from __future__ import annotations

import pandas as pd

from tymi.config.consistency import GENERATION_DEPS, consistency_fingerprint, pinned_deps
from tymi.config.spec import bootstrap_spec, load_spec, save_spec
from tymi.domain.artifacts import Column, Dataset, LogicalType, Schema
from tymi.profiling.profiler import profile_dataset
from tymi.synth.whole_db import generate_from_spec

_SCHEMA = Schema(
    columns=(
        Column("id", LogicalType.INTEGER, primary_key=True),
        Column("email", LogicalType.STRING),
    ),
    primary_key=("id",),
)

_FIXED_DEPS = {"tymi": "1.0.0", "numpy": "2.0.0", "pandas": "2.0.0", "faker": "1.0.0"}


def _spec(*, seed: int = 7, source_start: int = 0):
    profile = profile_dataset(
        Dataset(
            frame=pd.DataFrame(
                {
                    "id": range(source_start, source_start + 20),
                    "email": [f"u{i}@x.com" for i in range(20)],
                }
            ),
            schema=_SCHEMA,
        ),
        sensitive_columns=["email"],
        salt="s",
    )
    return bootstrap_spec({"customers": profile}, seed=seed)


# --- fingerprint stability + sensitivity (AC2) ------------------------------


def test_identical_unit_same_fingerprint_and_byte_identical_output() -> None:
    a, b = _spec(), _spec()
    assert consistency_fingerprint(a, deps=_FIXED_DEPS) == consistency_fingerprint(
        b, deps=_FIXED_DEPS
    )
    out_a = generate_from_spec(a)
    out_b = generate_from_spec(b)
    pd.testing.assert_frame_equal(out_a["customers"].frame, out_b["customers"].frame)


def test_seed_change_changes_fingerprint() -> None:
    assert consistency_fingerprint(_spec(seed=1), deps=_FIXED_DEPS) != consistency_fingerprint(
        _spec(seed=2), deps=_FIXED_DEPS
    )


def test_deps_change_changes_fingerprint() -> None:
    spec = _spec()
    other = dict(_FIXED_DEPS, numpy="9.9.9")
    assert consistency_fingerprint(spec, deps=_FIXED_DEPS) != consistency_fingerprint(
        spec, deps=other
    )


def test_shared_key_declaration_changes_fingerprint() -> None:
    base = _spec()
    changed = _spec()
    changed.tables["customers"].shared_keys = ["id"]
    changed.tables["customers"].reserved_key_block = 50
    assert consistency_fingerprint(base, deps=_FIXED_DEPS) != consistency_fingerprint(
        changed, deps=_FIXED_DEPS
    )


def test_profile_change_changes_fingerprint() -> None:
    # Same seed, different SOURCE data -> different pinned Profile -> different fingerprint.
    assert consistency_fingerprint(
        _spec(source_start=0), deps=_FIXED_DEPS
    ) != consistency_fingerprint(_spec(source_start=1000), deps=_FIXED_DEPS)


def test_tolerance_change_changes_fingerprint() -> None:
    # tolerance is part of the pinned unit (conservative): a change moves the fingerprint even
    # though it does not (yet) alter generation — the fidelity report (3.x) consumes it.
    base = _spec()
    changed = _spec()
    changed.tolerance = 0.5
    assert consistency_fingerprint(base, deps=_FIXED_DEPS) != consistency_fingerprint(
        changed, deps=_FIXED_DEPS
    )


def test_empty_spec_fingerprint_is_stable() -> None:
    empty = bootstrap_spec({}, seed=0)
    assert consistency_fingerprint(empty, deps=_FIXED_DEPS) == consistency_fingerprint(
        bootstrap_spec({}, seed=0), deps=_FIXED_DEPS
    )


# --- offline reuse: no re-profiling of the source (AC1) ---------------------


def test_offline_yaml_round_trip_keeps_fingerprint_and_generates(tmp_path) -> None:
    spec = _spec()
    before = consistency_fingerprint(spec, deps=_FIXED_DEPS)
    path = tmp_path / "spec.yaml"
    save_spec(spec, path)
    reloaded = load_spec(path)  # no source/adapter involved — bundled Profiles reused offline
    assert consistency_fingerprint(reloaded, deps=_FIXED_DEPS) == before
    # Same unit across the persistence boundary → byte-identical generation from bundled artifacts.
    pd.testing.assert_frame_equal(
        generate_from_spec(spec)["customers"].frame,
        generate_from_spec(reloaded)["customers"].frame,
    )


# --- pinned_deps -------------------------------------------------------------


def test_pinned_deps_reports_installed_generation_packages() -> None:
    deps = pinned_deps()
    assert set(deps) == set(GENERATION_DEPS)
    assert deps["numpy"] != "unknown" and deps["pandas"] != "unknown"  # actually installed
