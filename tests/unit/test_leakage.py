"""Story 2.5: leakage gate over declared sensitive columns."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from tymi.core.errors import ConfigError, LeakageError
from tymi.core.rng import make_rng
from tymi.domain.artifacts import (
    Column,
    Dataset,
    LeakageGuard,
    LogicalType,
    Schema,
    leakage_digest,
)
from tymi.profiling.profile_io import load_profile, save_profile
from tymi.profiling.profiler import build_leakage_guard, profile_dataset
from tymi.synth.generator import generate_faithful
from tymi.synth.leakage import enforce_leakage_gate

SALT = "fixed-test-salt"


def _dataset(frame: pd.DataFrame, columns: tuple[Column, ...]) -> Dataset:
    return Dataset(frame=frame, schema=Schema(columns=columns))


# --- digest + guard build (AC-1, AC-2) ------------------------------------


def test_leakage_digest_is_deterministic_and_salted() -> None:
    assert leakage_digest("a@x.com", SALT) == leakage_digest("a@x.com", SALT)
    assert leakage_digest("a@x.com", SALT) != leakage_digest("a@x.com", "other-salt")
    assert leakage_digest(5, SALT) == leakage_digest("5", SALT)  # stringified


def test_build_guard_hashes_distinct_values_only_no_raw() -> None:
    frame = pd.DataFrame({"email": ["a@x.com", "a@x.com", "b@x.com", None]})
    dataset = _dataset(frame, (Column("email", LogicalType.STRING),))
    guard = build_leakage_guard(dataset, ["email"], salt=SALT)
    assert guard is not None
    assert set(guard.columns["email"]) == {
        leakage_digest("a@x.com", SALT),
        leakage_digest("b@x.com", SALT),
    }
    # AD-6: no raw value appears anywhere in the guard.
    blob = repr(guard)
    assert "a@x.com" not in blob and "b@x.com" not in blob


def test_build_guard_datetime_hash_matches_gate_stringification() -> None:
    # Regression: source-side and gate-side stringification must agree for datetimes
    # ("2020-06-15" vs "2020-06-15 00:00:00") or a real value slips through unhashed.
    frame = pd.DataFrame({"born": pd.to_datetime(["2020-01-01", "2020-06-15"])})
    dataset = _dataset(frame, (Column("born", LogicalType.DATETIME),))
    guard = build_leakage_guard(dataset, ["born"], salt=SALT)
    assert guard is not None
    generated_value = pd.to_datetime(pd.Series(["2020-06-15"])).iloc[0]
    assert leakage_digest(generated_value, SALT) in set(guard.columns["born"])


def test_build_guard_none_when_no_sensitive() -> None:
    frame = pd.DataFrame({"email": ["a@x.com"]})
    dataset = _dataset(frame, (Column("email", LogicalType.STRING),))
    assert build_leakage_guard(dataset, [], salt=SALT) is None


def test_unknown_sensitive_column_raises() -> None:
    frame = pd.DataFrame({"email": ["a@x.com"]})
    dataset = _dataset(frame, (Column("email", LogicalType.STRING),))
    with pytest.raises(ConfigError, match="not found in the source table"):
        build_leakage_guard(dataset, ["nope"], salt=SALT)
    with pytest.raises(ConfigError, match="not found in the source table"):
        profile_dataset(dataset, sensitive_columns=["nope"])


def test_profile_dataset_auto_salt_varies() -> None:
    frame = pd.DataFrame({"email": ["a@x.com", "b@x.com"]})
    dataset = _dataset(frame, (Column("email", LogicalType.STRING),))
    p1 = profile_dataset(dataset, sensitive_columns=["email"])
    p2 = profile_dataset(dataset, sensitive_columns=["email"])
    assert p1.leakage_guard is not None and p2.leakage_guard is not None
    # auto salt is a per-Profile nonce → differs run to run
    assert p1.leakage_guard.salt != p2.leakage_guard.salt
    assert len(p1.leakage_guard.columns["email"]) == 2


# --- persistence round-trip (AC-2) ----------------------------------------


def test_profile_round_trip_preserves_guard(tmp_path) -> None:
    frame = pd.DataFrame({"email": ["a@x.com", "b@x.com"], "age": [1, 2]})
    dataset = _dataset(
        frame, (Column("email", LogicalType.STRING), Column("age", LogicalType.INTEGER))
    )
    profile = profile_dataset(dataset, sensitive_columns=["email"], salt=SALT)
    path = tmp_path / "p.yaml"
    save_profile(profile, path)
    loaded = load_profile(path)
    assert loaded.leakage_guard == profile.leakage_guard
    # the raw sensitive value is never written to disk
    text = path.read_text(encoding="utf-8")
    assert "a@x.com" not in text and "b@x.com" not in text


def test_profile_round_trip_no_guard(tmp_path) -> None:
    frame = pd.DataFrame({"age": [1, 2, 3]})
    dataset = _dataset(frame, (Column("age", LogicalType.INTEGER),))
    profile = profile_dataset(dataset)
    path = tmp_path / "p.yaml"
    save_profile(profile, path)
    assert load_profile(path).leakage_guard is None


# --- gate behaviour (AC-3, AC-4, AC-5) ------------------------------------


def _guard(values: list[str], column: str = "email", salt: str = SALT) -> LeakageGuard:
    return LeakageGuard(
        salt=salt, columns={column: tuple(sorted({leakage_digest(v, salt) for v in values}))}
    )


def test_gate_regenerates_only_colliding_cells() -> None:
    frame = pd.DataFrame({"email": ["real@x.com", "safe@x.com", "real@x.com"]})
    dataset = _dataset(frame, (Column("email", LogicalType.STRING),))
    guard = _guard(["real@x.com"])

    def resample(name: str, count: int, rng) -> list[str]:
        assert name == "email"
        return [f"synthetic{i}@x.com" for i in range(count)]

    out = enforce_leakage_gate(dataset, guard, rng=make_rng(0), resample=resample)
    col = list(out.frame["email"])
    # the safe cell is untouched; both colliding cells were replaced
    assert col[1] == "safe@x.com"
    assert col[0] != "real@x.com" and col[2] != "real@x.com"
    # nothing left in the output hashes into the real set
    digest_set = set(guard.columns["email"])
    assert all(leakage_digest(v, SALT) not in digest_set for v in col)


def test_gate_no_op_when_guard_none() -> None:
    frame = pd.DataFrame({"email": ["a@x.com"]})
    dataset = _dataset(frame, (Column("email", LogicalType.STRING),))

    def resample(name, count, rng):  # pragma: no cover - must not be called
        raise AssertionError("resample must not run when guard is None")

    out = enforce_leakage_gate(dataset, None, rng=make_rng(0), resample=resample)
    assert out is dataset


def test_gate_no_op_when_no_collision_returns_same_object() -> None:
    frame = pd.DataFrame({"email": ["safe@x.com"]})
    dataset = _dataset(frame, (Column("email", LogicalType.STRING),))
    guard = _guard(["real@x.com"])

    def resample(name, count, rng):  # pragma: no cover - no collision to fix
        raise AssertionError("no collision → resample must not run")

    out = enforce_leakage_gate(dataset, guard, rng=make_rng(0), resample=resample)
    assert out is dataset


def test_gate_ignores_nulls() -> None:
    frame = pd.DataFrame({"email": ["real@x.com", None]})
    dataset = _dataset(frame, (Column("email", LogicalType.STRING),))
    guard = _guard(["real@x.com"])

    def resample(name, count, rng):
        return ["clean@x.com"] * count

    out = enforce_leakage_gate(dataset, guard, rng=make_rng(0), resample=resample)
    assert out.frame["email"].iloc[0] == "clean@x.com"
    assert pd.isna(out.frame["email"].iloc[1])


def test_gate_fails_closed_when_unresolvable() -> None:
    frame = pd.DataFrame({"email": ["real@x.com"]})
    dataset = _dataset(frame, (Column("email", LogicalType.STRING),))
    guard = _guard(["real@x.com"])

    def resample(name, count, rng):  # every candidate still collides
        return ["real@x.com"] * count

    with pytest.raises(LeakageError, match="fails closed"):
        enforce_leakage_gate(dataset, guard, rng=make_rng(0), resample=resample, max_attempts=3)


# --- end to end through generate_faithful (AC-5, AC-6) --------------------


def _email_profile(salt: str = SALT):
    frame = pd.DataFrame({"email": [f"real{i}@x.com" for i in range(30)]})
    dataset = _dataset(frame, (Column("email", LogicalType.STRING),))
    return profile_dataset(dataset, sensitive_columns=["email"], salt=salt)


def test_generate_faithful_output_has_no_real_sensitive_value() -> None:
    profile = _email_profile()
    out = generate_faithful(profile, rows=50, rng=make_rng(7))
    digest_set = set(profile.leakage_guard.columns["email"])
    assert all(leakage_digest(v, SALT) not in digest_set for v in out.frame["email"])


def test_generate_faithful_gate_is_deterministic() -> None:
    profile = _email_profile()
    a = generate_faithful(profile, rows=50, rng=make_rng(7))
    b = generate_faithful(profile, rows=50, rng=make_rng(7))
    pd.testing.assert_frame_equal(a.frame, b.frame)


def test_sensitive_non_string_columns_store_no_raw_values() -> None:
    # AC-2: numeric/datetime/categorical/boolean sensitive columns must persist NO
    # real value (labels OR min/max order statistics) — they profile to counts only.
    from tymi.domain.artifacts import profile_to_json

    frame = pd.DataFrame(
        {
            "region": ["LATAM", "EMEA", "LATAM", "EMEA"],
            "salary": [50000, 91234, 73000, 60500],
            "born": pd.to_datetime(["1987-03-14", "1990-01-01", "2001-06-30", "1995-05-05"]),
            "flag": [True, False, True, False],
        }
    )
    dataset = _dataset(
        frame,
        (
            Column("region", LogicalType.CATEGORICAL),
            Column("salary", LogicalType.INTEGER),
            Column("born", LogicalType.DATETIME),
            Column("flag", LogicalType.BOOLEAN),
        ),
    )
    sensitive = ["region", "salary", "born", "flag"]
    profile = profile_dataset(dataset, sensitive_columns=sensitive, salt=SALT)
    by_name = {c.name: c for c in profile.columns}
    for name in sensitive:
        cp = by_name[name]
        assert cp.categories is None and cp.numeric is None
        assert cp.datetime is None and cp.text is None  # counts only
    # no real value (label, min/max salary, DOB boundary) appears in the artifact
    blob = profile_to_json(profile)
    for raw in ("LATAM", "EMEA", "91234", "50000", "1987-03-14", "2001-06-30"):
        assert raw not in blob

    # and such columns generate as typed-null (deferred to Epic 4), never a real value
    out = generate_faithful(profile, rows=20, rng=make_rng(1))
    for name in sensitive:
        assert out.frame[name].isna().all()


def _exhausted_string_profile():
    # A free-text column whose only real value is the empty string: the text sampler
    # can only ever emit "" (length 0), which is in the guard → cannot be resolved.
    frame = pd.DataFrame({"code": ["", "", ""]})
    dataset = _dataset(frame, (Column("code", LogicalType.STRING),))
    return profile_dataset(dataset, sensitive_columns=["code"], salt=SALT)


def test_generate_faithful_fails_closed_when_space_exhausted() -> None:
    with pytest.raises(LeakageError, match="fails closed"):
        generate_faithful(_exhausted_string_profile(), rows=20, rng=make_rng(1))


def _partial_collision_profile():
    # Single-letter free-text values {a, b} are the sensitive set; generation draws
    # length-1 strings from a 26-letter alphabet, so a and b DO get produced and must
    # be regenerated away — a non-vacuous exercise of the gate's success path.
    frame = pd.DataFrame({"c": ["a", "b", "a", "b"]})
    dataset = _dataset(frame, (Column("c", LogicalType.STRING),))
    return profile_dataset(dataset, sensitive_columns=["c"], salt=SALT)


def test_generate_faithful_regenerates_real_collisions_away() -> None:
    profile = _partial_collision_profile()
    out = generate_faithful(profile, rows=60, rng=make_rng(3))
    values = list(out.frame["c"])
    # Ungated, ~2/26 of 60 cells would be 'a'/'b'; their total absence proves the gate
    # actually regenerated the collisions (not a vacuous pass).
    assert "a" not in values and "b" not in values
    digest_set = set(profile.leakage_guard.columns["c"])
    assert all(leakage_digest(v, SALT) not in digest_set for v in values)


def test_gate_regeneration_is_deterministic() -> None:
    profile = _partial_collision_profile()
    a = generate_faithful(profile, rows=60, rng=make_rng(3))
    b = generate_faithful(profile, rows=60, rng=make_rng(3))
    pd.testing.assert_frame_equal(a.frame, b.frame)


# --- CLI surface (AC-5) ----------------------------------------------------


def test_cli_generate_fails_closed_exit_1(tmp_path) -> None:
    from typer.testing import CliRunner

    from tymi.cli.app import app

    path = tmp_path / "p.yaml"
    save_profile(_exhausted_string_profile(), path)
    result = CliRunner().invoke(app, ["generate", "-p", str(path), "-n", "5"])
    assert result.exit_code == 1
    assert "Leakage gate failed closed" in result.stdout


def test_cli_generate_email_guard_passes(tmp_path) -> None:
    from typer.testing import CliRunner

    from tymi.cli.app import app

    profile = _email_profile()
    path = tmp_path / "p.yaml"
    save_profile(profile, path)
    result = CliRunner().invoke(app, ["generate", "-p", str(path), "-n", "10"])
    assert result.exit_code == 0
    assert "email" in result.stdout


class _StubAdapter:
    def __init__(self, frame: pd.DataFrame, columns: tuple[Column, ...]) -> None:
        self._dataset = _dataset(frame, columns)

    def sample(self, table, *, rows, rng):  # noqa: ARG002 - signature match only
        return self._dataset


def _write_config(path: Path) -> None:
    path.write_text(
        "schema_version: '1.0.0'\n"
        "source:\n"
        "  engine: postgres\n"
        "  connection:\n"
        "    host: localhost\n"
        "  sensitive_columns: [email]\n",
        encoding="utf-8",
    )


def test_cli_profile_sensitive_merges_config_and_flag(tmp_path, monkeypatch) -> None:
    from typer.testing import CliRunner

    from tymi.cli import app as app_module

    cfg = tmp_path / "cfg.yaml"
    _write_config(cfg)
    frame = pd.DataFrame({"email": ["a@x.com", "b@x.com"], "age": [20, 30]})
    columns = (Column("email", LogicalType.STRING), Column("age", LogicalType.INTEGER))
    monkeypatch.setattr(
        app_module, "_load_adapter", lambda engine, config: _StubAdapter(frame, columns)
    )

    # --sensitive age (flag) unions with source.sensitive_columns=[email] (config)
    result = CliRunner().invoke(
        app_module.app, ["profile", "t", "-e", "postgres", "-c", str(cfg), "--sensitive", "age"]
    )
    assert result.exit_code == 0, result.stdout
    assert "leakage_guard" in result.stdout
    # both the config-declared and the flag-declared column are guarded
    import json

    guard = json.loads(result.stdout)["leakage_guard"]["columns"]
    assert set(guard) == {"email", "age"}


def test_cli_profile_unknown_sensitive_exits_1(tmp_path, monkeypatch) -> None:
    from typer.testing import CliRunner

    from tymi.cli import app as app_module

    cfg = tmp_path / "cfg.yaml"
    _write_config(cfg)
    frame = pd.DataFrame({"email": ["a@x.com"]})
    columns = (Column("email", LogicalType.STRING),)
    monkeypatch.setattr(
        app_module, "_load_adapter", lambda engine, config: _StubAdapter(frame, columns)
    )

    result = CliRunner().invoke(
        app_module.app, ["profile", "t", "-e", "postgres", "-c", str(cfg), "--sensitive", "nope"]
    )
    assert result.exit_code == 1
    assert "Invalid sensitive columns" in result.stdout


def test_cli_profile_load_with_sensitive_rejected(tmp_path) -> None:
    from typer.testing import CliRunner

    from tymi.cli.app import app

    profile = _email_profile()
    path = tmp_path / "p.yaml"
    save_profile(profile, path)
    result = CliRunner().invoke(app, ["profile", "--load", str(path), "--sensitive", "x"])
    assert result.exit_code == 2
    assert "cannot be combined with --load" in result.stdout
