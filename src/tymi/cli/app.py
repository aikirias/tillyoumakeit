"""TYMI command-line interface (driving adapter).

Some subcommands are still stubs (they exit with code 2). ``test-connection``
and ``schema`` are real. ``tymi --help`` lists them all and exits 0.
"""

from __future__ import annotations

from pathlib import Path

import typer

from tymi.chaos.policy import apply_policy
from tymi.config import load_config
from tymi.core.errors import (
    ChaosError,
    ConfigError,
    EngineConnectionError,
    EngineError,
    ExportError,
    GenerationError,
    LeakageError,
    ProfileError,
    TableNotFoundError,
)
from tymi.core.plugins import load_engines
from tymi.core.rng import make_rng
from tymi.domain.artifacts import (
    Dataset,
    fault_manifest_to_json,
    fidelity_report_to_json,
    manifest_audit_to_json,
    profile_to_json,
    schema_to_json,
)
from tymi.eval.chaos_audit import audit_manifest
from tymi.eval.fidelity import fidelity_report
from tymi.io.exporters import get_exporter
from tymi.profiling.profile_io import load_profile, save_profile
from tymi.profiling.profiler import profile_dataset
from tymi.synth.conditions import parse_conditions
from tymi.synth.generator import generate_faithful

app = typer.Typer(
    name="tymi",
    help="Fake It Till You Make It — faithful synthetic data + data chaos monkey.",
    no_args_is_help=True,
    add_completion=False,
)

_NOT_IMPLEMENTED_EXIT = 2

_STUB_COMMANDS = {
    "ui": "Launch the Streamlit web UI.",
}

_ENGINE_OPTION = typer.Option(..., "--engine", "-e", help="Engine name, e.g. 'postgres'.")
_CONFIG_OPTION = typer.Option(
    ..., "--config", "-c", exists=True, dir_okay=False, help="Path to the YAML config."
)


def _make_stub(command: str, summary: str):
    def _stub() -> None:
        typer.echo(f"'{command}' is not implemented yet ({summary})")
        raise typer.Exit(code=_NOT_IMPLEMENTED_EXIT)

    _stub.__doc__ = summary
    return _stub


for _name, _summary in _STUB_COMMANDS.items():
    app.command(name=_name)(_make_stub(_name, _summary))


def _load_adapter(engine: str, config: Path):
    """Load config and build the requested engine adapter, or exit non-zero."""
    try:
        cfg = load_config(config)
    except ConfigError as exc:
        typer.echo(f"Invalid config: {exc}")
        raise typer.Exit(code=2) from None

    if cfg.source.engine is not None and cfg.source.engine != engine:
        typer.echo(
            f"--engine {engine!r} does not match source.engine "
            f"{cfg.source.engine!r} in the config file."
        )
        raise typer.Exit(code=2)

    engines = load_engines()
    adapter_cls = engines.get(engine)
    if adapter_cls is None:
        typer.echo(f"Unknown engine {engine!r}. Available: {sorted(engines)}")
        raise typer.Exit(code=2)

    connection = cfg.source.connection
    if connection is None:
        typer.echo("No 'source.connection' section found in the config file.")
        raise typer.Exit(code=2)

    return adapter_cls(connection)


@app.command(name="test-connection")
def test_connection(engine: str = _ENGINE_OPTION, config: Path = _CONFIG_OPTION) -> None:
    """Test a connection to a source/destination engine."""
    adapter = _load_adapter(engine, config)
    try:
        adapter.test_connection()
    except EngineConnectionError as exc:
        typer.echo(f"Connection failed: {exc}")
        raise typer.Exit(code=1) from None
    typer.echo(f"Connection to {engine!r} OK.")


@app.command(name="schema")
def schema(
    table: str = typer.Argument(..., help="Table name to introspect."),
    engine: str = _ENGINE_OPTION,
    config: Path = _CONFIG_OPTION,
) -> None:
    """Introspect and print a table's schema as JSON."""
    adapter = _load_adapter(engine, config)
    try:
        result = adapter.introspect(table)
    except TableNotFoundError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from None
    except EngineConnectionError as exc:
        typer.echo(f"Connection failed: {exc}")
        raise typer.Exit(code=1) from None
    typer.echo(schema_to_json(result))


@app.command(name="sample")
def sample(
    table: str = typer.Argument(..., help="Table name to sample."),
    engine: str = _ENGINE_OPTION,
    config: Path = _CONFIG_OPTION,
    rows: int = typer.Option(1000, "--rows", "-n", min=1, help="Number of rows to sample."),
    seed: int = typer.Option(0, "--seed", "-s", help="Seed for reproducible sampling."),
) -> None:
    """Sample rows from a source table and print them as CSV."""
    adapter = _load_adapter(engine, config)
    if not adapter.reproducible_sample:
        typer.echo(f"Note: sampling for {engine!r} is not seed-reproducible.", err=True)
    try:
        dataset = adapter.sample(table, rows=rows, rng=make_rng(seed))
    except TableNotFoundError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from None
    except EngineConnectionError as exc:
        typer.echo(f"Connection failed: {exc}")
        raise typer.Exit(code=1) from None
    typer.echo(dataset.frame.to_csv(index=False))


@app.command(name="profile")
def profile(
    table: str | None = typer.Argument(None, help="Table to profile (omit with --load)."),
    engine: str | None = typer.Option(None, "--engine", "-e", help="Engine name, e.g. 'postgres'."),
    config: Path | None = typer.Option(
        None, "--config", "-c", exists=True, dir_okay=False, help="Path to the YAML config."
    ),
    rows: int = typer.Option(1000, "--rows", "-n", min=1, help="Rows to sample for the profile."),
    seed: int = typer.Option(0, "--seed", "-s", help="Seed for the sample."),
    out: Path | None = typer.Option(
        None, "--out", "-o", dir_okay=False, help="Write the Profile to a YAML file."
    ),
    load: Path | None = typer.Option(
        None,
        "--load",
        exists=True,
        dir_okay=False,
        help="Load and print a saved Profile YAML offline (no DB connection).",
    ),
    sensitive: list[str] = typer.Option(
        None,
        "--sensitive",
        help="Column whose real values must never leak; hashed into the Profile's "
        "leakage guard (repeatable, merged with source.sensitive_columns in config).",
    ),
    classify_pii: bool = typer.Option(
        False, "--classify-pii", help="Auto-detect Sensitive Columns from the sample (Story 4.1)."
    ),
) -> None:
    """Sample a table and build its Profile, or load a saved Profile offline.

    With ``--load`` the Profile is read from a file and printed with no source
    connection. Otherwise a table is sampled and profiled; ``-o`` saves the
    Profile to YAML instead of printing JSON. ``--sensitive`` columns are hashed
    into a leakage guard so the generator can prove no real value leaks (Story 2.5).
    """
    if load is not None:
        if out is not None:
            typer.echo("--out cannot be combined with --load.")
            raise typer.Exit(code=2)
        if sensitive:
            typer.echo(
                "--sensitive cannot be combined with --load "
                "(the guard is built at profile time)."
            )
            raise typer.Exit(code=2)
        try:
            loaded = load_profile(load)
        except ProfileError as exc:
            typer.echo(f"Could not load profile: {exc}")
            raise typer.Exit(code=1) from None
        typer.echo(profile_to_json(loaded))
        return

    if table is None or engine is None or config is None:
        typer.echo("profile requires TABLE, --engine and --config (or use --load FILE).")
        raise typer.Exit(code=2)

    adapter = _load_adapter(engine, config)
    # _load_adapter already validated the config loads; re-read it for the
    # declared sensitive columns and merge (union, order-preserving) with --sensitive.
    cfg = load_config(config)
    declared_sensitive = list(dict.fromkeys([*(sensitive or []), *cfg.source.sensitive_columns]))
    try:
        dataset = adapter.sample(table, rows=rows, rng=make_rng(seed))
    except TableNotFoundError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from None
    except EngineConnectionError as exc:
        typer.echo(f"Connection failed: {exc}")
        raise typer.Exit(code=1) from None

    try:
        result = profile_dataset(
            dataset,
            sensitive_columns=declared_sensitive,
            not_sensitive_columns=cfg.source.not_sensitive_columns,
            classify_pii=classify_pii,
        )
    except ConfigError as exc:
        typer.echo(f"Invalid sensitive columns: {exc}")
        raise typer.Exit(code=1) from None
    if out is not None:
        try:
            save_profile(result, out)
        except OSError as exc:
            typer.echo(f"Could not write profile: {exc}")
            raise typer.Exit(code=1) from None
        typer.echo(f"Profile written to {out} ({len(result.columns)} columns).")
    else:
        typer.echo(profile_to_json(result))


@app.command(name="generate")
def generate(
    profile_path: Path = typer.Option(
        ...,
        "--profile",
        "-p",
        exists=True,
        dir_okay=False,
        help="Path to a saved Profile YAML.",
    ),
    rows: int = typer.Option(1000, "--rows", "-n", min=1, help="Number of rows to generate."),
    seed: int = typer.Option(0, "--seed", "-s", help="Seed for reproducible generation."),
    where: list[str] = typer.Option(
        None,
        "--where",
        "-w",
        help="Condition a column: 'col=value', 'col in [lo,hi]' or 'col in {a,b,c}' "
        "(repeatable, one per column).",
    ),
    to: str = typer.Option(
        "csv", "--to", help="Export target: csv | json | parquet | sql."
    ),
    out: Path | None = typer.Option(
        None, "--out", "-o", dir_okay=False, help="Write the output to this file (files only)."
    ),
    engine: str | None = typer.Option(
        None, "--engine", "-e", help="Destination engine for '--to sql'."
    ),
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        exists=True,
        dir_okay=False,
        help="Destination config for '--to sql'.",
    ),
    table: str | None = typer.Option(
        None, "--table", "-t", help="Destination table for '--to sql'."
    ),
) -> None:
    """Generate faithful synthetic data from a saved Profile (offline) and export it.

    The Profile is loaded from a file with no source connection; each column's
    marginal distribution is reproduced and the source's numeric correlations are
    preserved via the in-house Gaussian copula. ``--where`` conditions a column so
    every row satisfies it while the other columns keep their distribution.

    ``--to csv|json|parquet`` writes a file (``--out``; CSV/JSON print to stdout
    without one), and ``--to sql --engine E --config C --table T`` loads the rows
    directly into any engine. Exports map from the canonical Schema (AR-10) and are
    byte-identical for a given Profile + seed (NFR-4).
    """
    try:
        loaded = load_profile(profile_path)
    except ProfileError as exc:
        typer.echo(f"Could not load profile: {exc}")
        raise typer.Exit(code=1) from None
    try:
        conditions = parse_conditions(where or [])
        dataset = generate_faithful(loaded, rows=rows, rng=make_rng(seed), conditions=conditions)
    except LeakageError as exc:
        typer.echo(f"Leakage gate failed closed: {exc}")
        raise typer.Exit(code=1) from None
    except GenerationError as exc:
        typer.echo(f"Invalid condition: {exc}")
        raise typer.Exit(code=1) from None
    except (ValueError, OverflowError) as exc:
        # A Profile can load yet carry invalid content (e.g. an unparsable or
        # out-of-range datetime bound); surface it cleanly instead of a traceback.
        typer.echo(f"Could not generate from profile: {exc}")
        raise typer.Exit(code=1) from None
    _export_dataset(dataset, to=to, out=out, engine=engine, config=config, table=table)


def _export_dataset(
    dataset,
    *,
    to: str,
    out: Path | None,
    engine: str | None,
    config: Path | None,
    table: str | None,
) -> None:
    """Export a generated Dataset per ``--to`` (file format or a direct SQL load)."""
    fmt = to.lower()
    if fmt == "sql":
        if not (engine and config and table):
            typer.echo("--to sql requires --engine, --config and --table.")
            raise typer.Exit(code=2)
        adapter = _load_adapter(engine, config)
        try:
            adapter.load(dataset, table=table)
        except EngineError as exc:
            typer.echo(f"Load failed: {exc}")
            raise typer.Exit(code=1) from None
        typer.echo(f"Loaded {len(dataset.frame)} rows into {table!r} on {engine!r}.")
        return

    try:
        exporter = get_exporter(fmt)
    except ExportError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=2) from None

    if out is None:
        if exporter.binary:
            typer.echo(f"--to {fmt} needs --out (binary format cannot print to stdout).")
            raise typer.Exit(code=2)
        typer.echo(exporter.render(dataset))
        return
    try:
        exporter.export(dataset, target=str(out))
    except ExportError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from None
    typer.echo(f"Wrote {len(dataset.frame)} rows to {out} ({fmt}).")


@app.command(name="report")
def report(
    profile_path: Path = typer.Option(
        ..., "--profile", "-p", exists=True, dir_okay=False, help="Path to a saved Profile YAML."
    ),
    fidelity: bool = typer.Option(
        False, "--fidelity", help="Produce a source-vs-generated fidelity report."
    ),
    data: Path | None = typer.Option(
        None,
        "--data",
        exists=True,
        dir_okay=False,
        help="Parquet of a generated Dataset to evaluate (else generate from the Profile).",
    ),
    rows: int = typer.Option(1000, "--rows", "-n", min=1, help="Rows to generate when no --data."),
    seed: int = typer.Option(0, "--seed", "-s", help="Seed for generation when no --data."),
    tolerance: float = typer.Option(
        0.9,
        "--tolerance",
        min=0.0,
        max=1.0,
        help="Pass threshold; exit 1 if any score is below it.",
    ),
    out: Path | None = typer.Option(
        None, "--out", "-o", dir_okay=False, help="Write the report JSON to a file."
    ),
) -> None:
    """Report source-vs-generated fidelity (KSComplement/TVComplement + correlation).

    Loads a saved Profile **offline** and scores a generated Dataset against the
    distribution the Profile captured. With ``--data`` the Dataset is read from a
    Parquet file; otherwise it is generated from the Profile (``--rows``/``--seed``).
    Exits **1** when any per-column score or the global metric is below ``--tolerance``
    (a CI gate), **0** otherwise.
    """
    if not fidelity:
        typer.echo("report currently supports only --fidelity.")
        raise typer.Exit(code=2)
    try:
        loaded = load_profile(profile_path)
    except ProfileError as exc:
        typer.echo(f"Could not load profile: {exc}")
        raise typer.Exit(code=1) from None

    if data is not None:
        import pandas as pd

        try:
            frame = pd.read_parquet(data)
        except Exception as exc:  # noqa: BLE001 - surface any read failure cleanly
            typer.echo(f"Could not read data file: {exc}")
            raise typer.Exit(code=1) from None
        dataset = Dataset(frame=frame, schema=loaded.schema)
    else:
        try:
            dataset = generate_faithful(loaded, rows=rows, rng=make_rng(seed))
        except (LeakageError, GenerationError, ValueError, OverflowError) as exc:
            typer.echo(f"Could not generate from profile: {exc}")
            raise typer.Exit(code=1) from None

    result = fidelity_report(loaded, dataset, tolerance=tolerance)
    payload = fidelity_report_to_json(result)
    if out is not None:
        try:
            Path(out).write_text(payload + "\n", encoding="utf-8")
        except OSError as exc:
            typer.echo(f"Could not write report: {exc}")
            raise typer.Exit(code=1) from None
        typer.echo(f"Fidelity report written to {out} (passed={result.passed}).")
    else:
        typer.echo(payload)
    if not result.passed:
        raise typer.Exit(code=1)


@app.command(name="chaos")
def chaos(
    profile_path: Path = typer.Option(
        ..., "--profile", "-p", exists=True, dir_okay=False, help="Path to a saved Profile YAML."
    ),
    config: Path = typer.Option(
        ..., "--config", "-c", exists=True, dir_okay=False, help="YAML config with a chaos policy."
    ),
    rows: int = typer.Option(1000, "--rows", "-n", min=1, help="Rows to generate before chaos."),
    seed: int = typer.Option(0, "--seed", "-s", help="Seed for reproducible chaos."),
    confirm: bool = typer.Option(
        False, "--confirm", help="Confirm a fully-chaotic run that breaks referential integrity."
    ),
    out: Path | None = typer.Option(
        None, "--out", "-o", dir_okay=False, help="Write the chaotic data CSV to a file."
    ),
    manifest_out: Path | None = typer.Option(
        None, "--manifest", dir_okay=False, help="Write the fault manifest JSON to a file."
    ),
    audit: bool = typer.Option(
        False, "--audit", help="Audit the manifest against the output (exit 1 if not faithful)."
    ),
) -> None:
    """Generate faithful data from a Profile, then apply the Config's Chaos Policy.

    In ``mixed`` mode a ``rate`` fraction of rows is corrupted (the rest stay faithful);
    ``fully_chaotic`` corrupts the whole table and, over a table with foreign keys,
    requires ``--confirm``. Emits the chaotic data as CSV; ``--manifest`` writes the
    auditable fault manifest.
    """
    try:
        loaded = load_profile(profile_path)
    except ProfileError as exc:
        typer.echo(f"Could not load profile: {exc}")
        raise typer.Exit(code=1) from None
    try:
        cfg = load_config(config)
    except ConfigError as exc:
        typer.echo(f"Invalid config: {exc}")
        raise typer.Exit(code=2) from None

    rng = make_rng(seed if cfg.seed is None else cfg.seed)
    try:
        dataset = generate_faithful(loaded, rows=rows, rng=rng)
        chaotic, manifest = apply_policy(dataset, cfg.chaos, rng=rng, confirmed=confirm)
    except (ChaosError, GenerationError, LeakageError) as exc:
        typer.echo(f"Chaos run failed: {exc}")
        raise typer.Exit(code=1) from None

    audit_failed = False
    if audit:
        result = audit_manifest(dataset, chaotic, manifest)
        typer.echo(manifest_audit_to_json(result), err=True)
        audit_failed = not result.valid

    if manifest_out is not None:
        try:
            Path(manifest_out).write_text(fault_manifest_to_json(manifest) + "\n", encoding="utf-8")
        except OSError as exc:
            typer.echo(f"Could not write manifest: {exc}")
            raise typer.Exit(code=1) from None
    payload = chaotic.frame.to_csv(index=False)
    if out is not None:
        try:
            Path(out).write_text(payload, encoding="utf-8")
        except OSError as exc:
            typer.echo(f"Could not write data: {exc}")
            raise typer.Exit(code=1) from None
        typer.echo(f"Wrote {len(chaotic.frame)} rows to {out}; {len(manifest.entries)} faults.")
    else:
        typer.echo(payload)
    if audit_failed:
        typer.echo("Manifest audit FAILED: the manifest is not a faithful record.", err=True)
        raise typer.Exit(code=1)


if __name__ == "__main__":  # pragma: no cover
    app()
