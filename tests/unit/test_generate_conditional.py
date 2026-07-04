"""AC-2/AC-3/AC-4/AC-6 (2.4): conditional generation end-to-end (no DB)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from typer.testing import CliRunner

from tymi.cli.app import app
from tymi.core.errors import GenerationError
from tymi.core.rng import make_rng
from tymi.domain.artifacts import (
    CategoryFrequency,
    Column,
    ColumnProfile,
    Dataset,
    LogicalType,
    Profile,
    Schema,
)
from tymi.profiling.profile_io import save_profile
from tymi.profiling.profiler import profile_dataset
from tymi.synth.conditions import Between, Equals, Members
from tymi.synth.generator import generate_faithful


def _source() -> Dataset:
    rng = np.random.default_rng(7)
    n = 3000
    x = rng.normal(0.0, 1.0, size=n)
    frame = pd.DataFrame(
        {
            "region": rng.choice(["LATAM", "EMEA", "APAC"], size=n, p=[0.5, 0.3, 0.2]),
            "age": rng.integers(18, 80, size=n),
            "x": x,
            "y": 2.0 * x + rng.normal(0.0, 0.3, size=n),  # strong positive corr with x
            "email": [f"user{i}@corp.com" for i in range(n)],
        }
    )
    schema = Schema(
        columns=(
            Column("region", LogicalType.CATEGORICAL),
            Column("age", LogicalType.INTEGER),
            Column("x", LogicalType.FLOAT),
            Column("y", LogicalType.FLOAT),
            Column("email", LogicalType.STRING),
        )
    )
    return Dataset(frame=frame, schema=schema)


def test_equality_condition_pins_every_row() -> None:
    profile = profile_dataset(_source())
    ds = generate_faithful(
        profile, rows=500, rng=make_rng(0), conditions={"region": Equals("region", "LATAM")}
    )
    assert (ds.frame["region"] == "LATAM").all()  # AC-2: 100%
    assert ds.frame["region"].notna().all()  # no null slips through


def test_range_condition_all_rows_in_range() -> None:
    profile = profile_dataset(_source())
    ds = generate_faithful(
        profile, rows=1000, rng=make_rng(0), conditions={"age": Between("age", "25", "35")}
    )
    age = ds.frame["age"]
    assert age.notna().all()
    assert (age >= 25).all() and (age <= 35).all()  # AC-2 + AC-4 in-range


def test_range_condition_is_truncated_not_uniform() -> None:
    # AC-4: within the range the histogram shape survives. The source age is uniform
    # over [18,80), so a [25,35] slice is ~uniform → mean near the midpoint; the key
    # property we assert is the values are genuinely spread, not pinned to an edge.
    profile = profile_dataset(_source())
    ds = generate_faithful(
        profile, rows=2000, rng=make_rng(1), conditions={"age": Between("age", "25", "35")}
    )
    age = ds.frame["age"]
    assert age.nunique() > 5  # spread across the range, not a constant
    assert 27.0 < age.mean() < 33.0  # centered inside [25,35]


def test_membership_condition_restricts_categories() -> None:
    profile = profile_dataset(_source())
    ds = generate_faithful(
        profile,
        rows=2000,
        rng=make_rng(0),
        conditions={"region": Members("region", ("LATAM", "EMEA"))},
    )
    assert set(ds.frame["region"].unique()) <= {"LATAM", "EMEA"}
    # source proportions among the allowed labels (0.5 vs 0.3) are roughly kept
    share_latam = (ds.frame["region"] == "LATAM").mean()
    assert 0.55 < share_latam < 0.70  # 0.5/0.8 = 0.625


def test_non_conditioned_columns_keep_distribution() -> None:
    # AC-3: conditioning on region must not distort the age marginal.
    profile = profile_dataset(_source())
    ds = generate_faithful(
        profile, rows=4000, rng=make_rng(0), conditions={"region": Equals("region", "LATAM")}
    )
    by = {c.name: c for c in profile.columns}
    age = ds.frame["age"].dropna()
    assert abs(age.mean() - by["age"].numeric.mean) < 3.0
    assert age.min() >= by["age"].numeric.min - 1e-9
    assert age.max() <= by["age"].numeric.max + 1e-9


def test_non_conditioned_correlation_preserved_under_condition() -> None:
    # AC-3: the x/y copula correlation still holds when we condition region.
    profile = profile_dataset(_source())
    ds = generate_faithful(
        profile, rows=4000, rng=make_rng(0), conditions={"region": Equals("region", "LATAM")}
    )
    xy = ds.frame[["x", "y"]].corr(method="spearman").loc["x", "y"]
    assert xy > 0.85


def test_conditioned_string_column_not_clobbered_by_faker() -> None:
    # AC-2: a pinned email column keeps the condition value, Faker does not override.
    profile = profile_dataset(_source())
    ds = generate_faithful(
        profile,
        rows=200,
        rng=make_rng(0),
        conditions={"email": Equals("email", "fixed@example.com")},
    )
    assert (ds.frame["email"] == "fixed@example.com").all()


def test_conditional_generation_deterministic() -> None:
    profile = profile_dataset(_source())
    conditions = {"age": Between("age", "25", "35"), "region": Members("region", ("LATAM", "EMEA"))}
    a = generate_faithful(profile, rows=800, rng=make_rng(9), conditions=conditions)
    b = generate_faithful(profile, rows=800, rng=make_rng(9), conditions=conditions)
    assert_frame_equal(a.frame, b.frame)


def test_unknown_column_condition_raises() -> None:
    profile = profile_dataset(_source())
    with pytest.raises(GenerationError, match="unknown column"):
        generate_faithful(
            profile, rows=10, rng=make_rng(0), conditions={"nope": Equals("nope", "x")}
        )


def test_range_on_categorical_raises() -> None:
    profile = profile_dataset(_source())
    with pytest.raises(GenerationError, match="range condition on non-numeric"):
        generate_faithful(
            profile, rows=10, rng=make_rng(0), conditions={"region": Between("region", "a", "b")}
        )


def test_non_numeric_range_value_raises() -> None:
    profile = profile_dataset(_source())
    with pytest.raises(GenerationError, match="not numeric"):
        generate_faithful(
            profile, rows=10, rng=make_rng(0), conditions={"age": Between("age", "young", "old")}
        )


# --- AC-4: range truncation is faithful (not flat uniform) ----------------


def _skewed_source() -> Dataset:
    rng = np.random.default_rng(3)
    frame = pd.DataFrame({"amount": rng.exponential(scale=10.0, size=6000)})  # right-skewed
    return Dataset(frame=frame, schema=Schema(columns=(Column("amount", LogicalType.FLOAT),)))


def test_range_condition_follows_truncated_histogram_not_uniform() -> None:
    # AC-4: on a right-skewed source, an in-range [0,30] slice must keep the
    # decreasing density — its median sits well below the 15.0 range midpoint. A
    # flat-uniform sampler would land the median near 15.0, so this discriminates.
    source = _skewed_source()
    profile = profile_dataset(source)
    ds = generate_faithful(
        profile, rows=6000, rng=make_rng(0), conditions={"amount": Between("amount", "0", "30")}
    )
    amount = ds.frame["amount"]
    assert (amount >= 0).all() and (amount <= 30).all()
    gen_median = amount.median()
    src = source.frame["amount"]
    src_median = src[(src >= 0) & (src <= 30)].median()  # true conditional median
    assert gen_median < 12.0  # skew preserved, not the 15.0 uniform midpoint
    assert abs(gen_median - src_median) < 2.5  # matches the truncated histogram


def test_numeric_range_condition_preserves_copula_correlation() -> None:
    # AC-3/AC-4: conditioning a column that IS in the copula with a range must keep
    # its partner's correlation (the monotone CDF remap preserves rank order).
    profile = profile_dataset(_source())
    ds = generate_faithful(
        profile, rows=5000, rng=make_rng(0), conditions={"x": Between("x", "-1", "3")}
    )
    assert (ds.frame["x"] >= -1).all() and (ds.frame["x"] <= 3).all()
    xy = ds.frame[["x", "y"]].corr(method="spearman").loc["x", "y"]
    assert xy > 0.7  # copula correlation survives the truncation


# --- AC-2: datetime + boolean conditioned columns (100%, no null) ---------


def _dt_bool_source() -> Dataset:
    rng = np.random.default_rng(5)
    n = 1500
    days = rng.integers(0, 900, size=n)
    frame = pd.DataFrame(
        {
            "created": pd.Timestamp("2020-01-01") + pd.to_timedelta(days, unit="D"),
            "active": rng.choice([True, False], size=n),
        }
    )
    schema = Schema(
        columns=(
            Column("created", LogicalType.DATETIME),
            Column("active", LogicalType.BOOLEAN),
        )
    )
    return Dataset(frame=frame, schema=schema)


def test_datetime_range_condition_all_in_range_no_null() -> None:
    profile = profile_dataset(_dt_bool_source())
    lo, hi = pd.Timestamp("2020-06-01"), pd.Timestamp("2020-09-01")
    ds = generate_faithful(
        profile,
        rows=800,
        rng=make_rng(0),
        conditions={"created": Between("created", "2020-06-01", "2020-09-01")},
    )
    created = ds.frame["created"]
    assert created.notna().all()
    assert (created >= lo).all() and (created <= hi).all()


def test_boolean_equality_condition_all_true_no_null() -> None:
    profile = profile_dataset(_dt_bool_source())
    ds = generate_faithful(
        profile, rows=500, rng=make_rng(0), conditions={"active": Equals("active", "true")}
    )
    assert ds.frame["active"].notna().all()
    assert (ds.frame["active"]).all()


def test_boolean_invalid_value_raises() -> None:
    # regression: a boolean condition value must be validated, not silently → False.
    profile = profile_dataset(_dt_bool_source())
    with pytest.raises(GenerationError, match="not a boolean"):
        generate_faithful(
            profile, rows=10, rng=make_rng(0), conditions={"active": Equals("active", "maybe")}
        )


def test_integer_membership_non_integral_raises() -> None:
    # regression: an integer membership value must not be silently rounded.
    profile = profile_dataset(_source())
    with pytest.raises(GenerationError, match="whole number"):
        generate_faithful(
            profile, rows=10, rng=make_rng(0), conditions={"age": Members("age", ("10.5", "20.5"))}
        )


def test_membership_generates_label_outside_top_k() -> None:
    # regression: an explicitly requested label unseen in the profiled categories
    # must still be generated (add-one smoothing), not floored to zero.
    profile = profile_dataset(_source())
    ds = generate_faithful(
        profile,
        rows=3000,
        rng=make_rng(0),
        conditions={"region": Members("region", ("LATAM", "ZZZ"))},
    )
    values = set(ds.frame["region"].unique())
    assert values <= {"LATAM", "ZZZ"}
    assert "ZZZ" in values  # the unseen requested label appears


def test_condition_on_unprofiled_schema_column_raises() -> None:
    # regression (HIGH): a schema column with no ColumnProfile must not be emitted
    # as a silent all-null column that ignores the condition — it must raise.
    schema = Schema(columns=(Column("region", LogicalType.CATEGORICAL),))
    profile = Profile(schema=schema, columns=())  # schema present, no profiled stats
    with pytest.raises(GenerationError, match="no profiled statistics"):
        generate_faithful(
            profile, rows=10, rng=make_rng(0), conditions={"region": Equals("region", "LATAM")}
        )


def test_profiled_condition_column_still_works_when_schemaless() -> None:
    # a profiled-but-schemaless column is still conditionable (drives from columns).
    profile = Profile(
        schema=Schema(),
        columns=(
            ColumnProfile(
                name="region",
                logical_type=LogicalType.CATEGORICAL,
                count=3,
                null_count=0,
                distinct_count=2,
                categories=(CategoryFrequency("A", 2), CategoryFrequency("B", 1)),
            ),
        ),
    )
    ds = generate_faithful(
        profile, rows=50, rng=make_rng(0), conditions={"region": Equals("region", "A")}
    )
    assert (ds.frame["region"] == "A").all()


# --- AC-5: the CLI surface fails cleanly (exit 1, no traceback) -----------


def test_cli_where_valid_and_invalid(tmp_path) -> None:
    profile = profile_dataset(_source())
    profile_file = tmp_path / "p.yaml"
    save_profile(profile, profile_file)
    runner = CliRunner()

    ok = runner.invoke(
        app,
        ["generate", "-p", str(profile_file), "-n", "20", "-w", "region=LATAM", "-w",
         "age in [20,30]"],
    )
    assert ok.exit_code == 0
    lines = [line for line in ok.output.splitlines() if line and not line.startswith("region")]
    assert all(line.startswith("LATAM,") for line in lines)

    bad = runner.invoke(app, ["generate", "-p", str(profile_file), "-w", "nope=x"])
    assert bad.exit_code == 1
    assert "Invalid condition" in bad.output
    assert "Traceback" not in bad.output
