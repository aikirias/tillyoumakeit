"""Fidelity report — in-house KSComplement / TVComplement / CorrelationSimilarity.

Compares a generated Dataset against the source distribution captured in the Profile
(AD-6: aggregates only, never raw rows). Uses SDMetrics' well-known metric
definitions, computed in-house on ``scipy.stats`` + numpy: ``sdmetrics`` transitively
depends on ``copulas`` (BUSL-1.1), which AD-9 excludes — the same reason Story 2.2
built an in-house Gaussian copula rather than vendoring the Copulas library.

- **KSComplement** (numeric / datetime): ``1 − D``, the two-sample Kolmogorov–Smirnov
  complement between the generated column and a **reference sample reconstructed from
  the Profile** with the same marginal sampler the generator uses
  (``generate_marginals``). Two-sample (like SDMetrics) — not a one-sample fit against
  a continuous histogram CDF — so a discrete, constant or low-cardinality column is
  scored fairly and a faithful column scores ≈ 1 rather than being penalised for the
  step-vs-linear-CDF mismatch. Datetime is compared on its epoch (the generator
  reproduces the observed range; monthly seasonality generation is deferred, PRD v2,
  so it is deliberately not the thing measured).
- **TVComplement** (categorical / boolean): ``1 − ½·Σ|p_gen − p_ref|`` between the
  generated category frequencies and the Profile's stored (exact) frequencies — the
  frequencies the generator reproduces faithfully.
- **CorrelationSimilarity** (global): ``1 − |ρ_source − ρ_gen| / 2`` averaged over the
  numeric column pairs, comparing the generated Spearman matrix to the stored one.

All scores are in ``[0, 1]`` (1 = identical). A run **passes** only if at least one
column was compared and every score + the global metric are ``>= tolerance``; the
failing columns are listed so a CI gate can act on them. Deterministic: the reference
is reconstructed from a fixed internal seed, so a given (Profile, Dataset) always
yields the same report.
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd
from scipy.stats import ks_2samp

from tymi.core.rng import make_rng
from tymi.domain.artifacts import ColumnProfile, Dataset, FidelityReport, Profile
from tymi.synth.marginals import generate_marginals

#: Sentinel listed in ``failures`` when the global correlation metric is below tolerance.
CORRELATION_KEY = "__correlation__"

#: Fixed seed + minimum size for the reconstructed reference sample (deterministic
#: report; a large reference keeps the two-sample KS stable/low-noise).
_REFERENCE_SEED = 0
_REFERENCE_ROWS = 2000
_ROUND = 6


def fidelity_report(
    profile: Profile, dataset: Dataset, *, tolerance: float = 0.9
) -> FidelityReport:
    """Score each column + the global correlation of ``dataset`` against ``profile``."""
    frame = dataset.frame
    reference = generate_marginals(
        profile, rows=max(_REFERENCE_ROWS, len(frame)), rng=make_rng(_REFERENCE_SEED)
    ).frame

    raw_scores: dict[str, float] = {}
    skipped: list[str] = []
    for cp in profile.columns:
        if cp.name not in frame.columns:
            continue
        ref_col = reference[cp.name] if cp.name in reference.columns else None
        score = _column_score(cp, frame[cp.name].dropna(), ref_col)
        if score is None:
            skipped.append(cp.name)
        else:
            raw_scores[cp.name] = score

    global_raw = correlation_similarity(dataset, profile)
    failures = [name for name, score in raw_scores.items() if score < tolerance]
    if global_raw is not None and global_raw < tolerance:
        failures.append(CORRELATION_KEY)
    # A report that compared nothing (e.g. --data whose columns don't match the
    # Profile) must NOT pass — that would green-light a wrong/empty dataset.
    compared = bool(raw_scores) or global_raw is not None
    return FidelityReport(
        per_column={name: round(score, _ROUND) for name, score in raw_scores.items()},
        global_correlation=None if global_raw is None else round(global_raw, _ROUND),
        tolerance=tolerance,
        passed=compared and not failures,
        failures=tuple(failures),
        skipped=tuple(skipped),
    )


def _column_score(
    cp: ColumnProfile, column: pd.Series, reference: pd.Series | None
) -> float | None:
    """Pick the metric for a column by the stats the Profile actually stored."""
    if cp.numeric is not None:
        if reference is None:
            return None
        return ks_complement(
            pd.to_numeric(reference, errors="coerce"), pd.to_numeric(column, errors="coerce")
        )
    if cp.categories is not None:
        ref = {str(c.value): float(c.count) for c in cp.categories}
        gen = {str(k): float(v) for k, v in column.astype(str).value_counts().items()}
        return tv_complement(gen, ref)
    if cp.datetime is not None:
        if reference is None:
            return None
        ref_epoch = _epoch(reference)
        gen_epoch = _epoch(column)
        return ks_complement(ref_epoch, gen_epoch)
    # text (length stats only) — no comparable distribution.
    return None


def ks_complement(reference: pd.Series, generated: pd.Series) -> float | None:
    """``1 − D`` — two-sample KS complement between a reference and a generated column."""
    ref = np.asarray(reference, dtype=float)
    ref = ref[np.isfinite(ref)]
    gen = np.asarray(generated, dtype=float)
    gen = gen[np.isfinite(gen)]
    if ref.size == 0 or gen.size == 0:
        return None
    return 1.0 - float(ks_2samp(ref, gen).statistic)


def tv_complement(gen: Mapping[str, float], ref: Mapping[str, float]) -> float | None:
    """``1 − ½·Σ|p_gen − p_ref|`` over the union of categories."""
    gen_total = float(sum(gen.values()))
    ref_total = float(sum(ref.values()))
    if gen_total <= 0 or ref_total <= 0:
        return None
    categories = set(gen) | set(ref)
    tvd = 0.5 * sum(
        abs(gen.get(c, 0.0) / gen_total - ref.get(c, 0.0) / ref_total) for c in categories
    )
    return 1.0 - tvd


def correlation_similarity(dataset: Dataset, profile: Profile) -> float | None:
    """Mean ``1 − |ρ_source − ρ_gen| / 2`` over the stored numeric column pairs."""
    correlations = profile.correlations
    matrix = correlations.numeric if correlations is not None else None
    if matrix is None or len(matrix.columns) < 2:
        return None
    frame = dataset.frame
    present = [c for c in matrix.columns if c in frame.columns]
    if len(present) < 2:
        return None
    numeric = frame[present].apply(pd.to_numeric, errors="coerce")
    gen_corr = numeric.corr(method="spearman")

    sims: list[float] = []
    for i, ci in enumerate(matrix.columns):
        for j in range(i + 1, len(matrix.columns)):
            cj = matrix.columns[j]
            ref = matrix.matrix[i][j]
            if ref is None or ci not in gen_corr.columns or cj not in gen_corr.columns:
                continue
            gen = gen_corr.loc[ci, cj]
            if pd.isna(gen):
                continue
            sims.append(1.0 - abs(float(ref) - float(gen)) / 2.0)
    return float(np.mean(sims)) if sims else None


def _epoch(column: pd.Series) -> pd.Series:
    """Datetime column → int64 nanoseconds since epoch (NaT dropped), for KS."""
    return pd.to_datetime(column, errors="coerce").dropna().astype("int64")
