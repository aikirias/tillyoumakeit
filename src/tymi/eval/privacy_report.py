"""Quality & Privacy report — composite fidelity + in-house privacy metrics (Story 4.3).

Assembles, from a generated Dataset and the source Profile alone (AD-6: aggregates +
hashed guard, never raw rows):

- **Composite Quality Score** — one ``[0, 1]`` number: the mean of the Story 2.7
  per-column fidelity scores and the global CorrelationSimilarity. The full
  :class:`~tymi.domain.artifacts.FidelityReport` is embedded for drill-down.
- **Membership-disclosure metric** — the share of generated values in sensitive columns
  that exactly reproduce a real source value, measured against the Profile's hashed
  :class:`~tymi.domain.artifacts.LeakageGuard` (Story 2.5). No raw value is compared —
  only keyed digests — so AD-6 holds. A properly gated faithful run scores ~0; this
  doubles as a check that the leakage gate held and still catches leakage in an
  externally supplied ``--data`` Parquet.
- **Attribute-inference metric** — a conservative upper-bound proxy of how well an
  attacker who knows the other (quasi-identifier) columns could infer a sensitive
  column's value, computed on the *released* (generated) data: max |Spearman ρ| to
  another numeric column for a numeric target, or the best conditional-mode accuracy from
  a low-cardinality predictor for a categorical target.

In-house on numpy/pandas (AD-9: no ``sdmetrics`` → ``copulas`` BUSL-1.1), exactly as
Story 2.7 built the fidelity metrics. Deterministic for a given (Profile, Dataset).
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from tymi.domain.artifacts import (
    Dataset,
    FidelityReport,
    LogicalType,
    Profile,
    QualityPrivacyReport,
    leakage_digest,
)
from tymi.eval.fidelity import fidelity_report

_ROUND = 6
#: A predictor with more distinct values than this is skipped for attribute inference:
#: a near-unique column (an ID) trivially "predicts" any target and would inflate the
#: metric without reflecting real inference risk.
_MAX_PREDICTOR_CARDINALITY = 50
#: Minimum paired rows before a Spearman correlation is meaningful (2 points → ±1).
_MIN_CORRELATION_ROWS = 5

_NUMERIC = frozenset({LogicalType.INTEGER, LogicalType.FLOAT})


def quality_privacy_report(
    profile: Profile,
    dataset: Dataset,
    *,
    tolerance: float = 0.9,
    membership_threshold: float = 0.0,
    attribute_threshold: float = 1.0,
) -> QualityPrivacyReport:
    """Compose the Quality Score + privacy metrics with a configurable CI gate."""
    fidelity = fidelity_report(profile, dataset, tolerance=tolerance)
    quality = quality_score(fidelity)
    sensitive = list(profile.leakage_guard.columns) if profile.leakage_guard else []

    membership = membership_risk(profile, dataset)
    attribute = attribute_inference_risk(dataset, sensitive)

    # A non-finite quality (only reachable from a directly-injected FidelityReport, not the
    # pipeline) must not slip the gate: ``nan < tolerance`` is False, which would silently
    # pass. Treat it as "nothing comparable".
    quality_ok = quality is not None and math.isfinite(quality)
    failures: list[str] = []
    # A report that could compare nothing (quality None) must not pass — same rule as 2.7.
    if not quality_ok or quality < tolerance:
        failures.append("quality")
    if membership is not None and membership > membership_threshold:
        failures.append("membership")
    if attribute is not None and attribute > attribute_threshold:
        failures.append("attribute_inference")

    return QualityPrivacyReport(
        quality_score=round(quality, _ROUND) if quality_ok else None,
        membership_risk=None if membership is None else round(membership, _ROUND),
        attribute_inference_risk=None if attribute is None else round(attribute, _ROUND),
        quality_tolerance=tolerance,
        membership_threshold=membership_threshold,
        attribute_threshold=attribute_threshold,
        passed=not failures,
        failures=tuple(failures),
        fidelity=fidelity,
    )


def quality_score(fidelity: FidelityReport) -> float | None:
    """Composite ``[0, 1]`` score: mean of the per-column scores + global correlation."""
    scores = list(fidelity.per_column.values())
    if fidelity.global_correlation is not None:
        scores.append(fidelity.global_correlation)
    return float(np.mean(scores)) if scores else None


def membership_risk(profile: Profile, dataset: Dataset) -> float | None:
    """Share of generated sensitive values that exactly reproduce a real source value.

    Compared via the hashed :class:`LeakageGuard` (keyed digests only, AD-6). ``None``
    when there is no guard or none of its columns are present with checkable values.
    """
    guard = profile.leakage_guard
    if guard is None:
        return None
    frame = dataset.frame
    # Worst-column disclosure rate, NOT a pooled average across columns: pooling would let
    # a fully-leaked sensitive column be masked by other safe columns (a 100%-leaked column
    # + a clean one averages to 0.5 and slips a relaxed threshold). Max is also consistent
    # with attribute_inference_risk's worst-case reporting.
    rates: list[float] = []
    for name, digests in guard.columns.items():
        if name not in frame.columns or not digests:
            continue
        digest_set = set(digests)
        # ``astype(object)`` first (Story 2.6 fix): a nullable ``Int64`` holding ``pd.NA``
        # upcasts to float under most ops, so ``100`` would hash as ``"100.0"`` and miss
        # the guard's ``"100"`` digest. Object dtype preserves each scalar's real type.
        column = frame[name].astype(object)
        values = column[column.map(lambda v: bool(pd.notna(v)))]
        if values.empty:
            continue
        digests_gen = values.map(lambda v: leakage_digest(v, guard.salt))
        rates.append(int(digests_gen.isin(digest_set).sum()) / int(values.size))
    return max(rates) if rates else None


def attribute_inference_risk(
    dataset: Dataset, sensitive_columns: list[str]
) -> float | None:
    """Worst-case per-sensitive-column inference signal on the released data.

    Numeric target → max |Spearman ρ| to another numeric column; categorical/text target
    → best conditional-mode accuracy from a low-cardinality predictor. ``None`` when no
    sensitive column yields a computable signal.
    """
    frame = dataset.frame
    types = {c.name: c.logical_type for c in dataset.schema.columns}
    risks: list[float] = []
    for name in sensitive_columns:
        if name not in frame.columns:
            continue
        if types.get(name) in _NUMERIC:
            risk = _max_numeric_correlation(frame, name, types)
        else:
            risk = _max_conditional_mode_accuracy(frame, name)
        if risk is not None:
            risks.append(risk)
    return max(risks) if risks else None


def _max_numeric_correlation(
    frame: pd.DataFrame, target: str, types: dict[str, LogicalType]
) -> float | None:
    """Max |Spearman ρ| between the numeric ``target`` and any other numeric column."""
    others = [
        c for c in frame.columns if c != target and types.get(c) in _NUMERIC
    ]
    if not others:
        return None
    tgt = pd.to_numeric(frame[target], errors="coerce")
    best: float | None = None
    for other in others:
        pair = pd.DataFrame({"t": tgt, "o": pd.to_numeric(frame[other], errors="coerce")})
        pair = pair.dropna()
        # Need real support: Spearman on 2 distinct points is always ±1, a meaningless
        # extreme; require a minimum sample before reporting a correlation.
        if len(pair) < _MIN_CORRELATION_ROWS or pair["t"].nunique() < 2 or pair["o"].nunique() < 2:
            continue
        rho = pair["t"].corr(pair["o"], method="spearman")
        if pd.isna(rho):
            continue
        best = abs(float(rho)) if best is None else max(best, abs(float(rho)))
    return best


def _max_conditional_mode_accuracy(frame: pd.DataFrame, target: str) -> float | None:
    """Best accuracy of guessing ``target`` from a single low-cardinality predictor.

    For each candidate predictor, group by it and predict each group's most frequent
    target value; accuracy is the share of rows guessed right. High accuracy means an
    attacker who knows that column can infer the sensitive value.
    """
    best: float | None = None
    for predictor in frame.columns:
        if predictor == target:
            continue
        pair = pd.DataFrame(
            {"t": frame[target].astype(object), "p": frame[predictor].astype(object)}
        ).dropna()
        if pair.empty:
            continue
        cardinality = pair["p"].nunique()
        # Skip a near-unique predictor: an ID-like column (cardinality cap) or one whose
        # groups average < 2 rows would "predict" the target trivially by group-of-one,
        # saturating the metric to 1.0 without reflecting real inference risk.
        if cardinality > _MAX_PREDICTOR_CARDINALITY or len(pair) < 2 * cardinality:
            continue
        # Per predictor group, the count of the most frequent target value.
        group_hits = pair.groupby("p", sort=False)["t"].agg(
            lambda s: int(s.value_counts().iloc[0])
        )
        accuracy = float(group_hits.sum()) / float(len(pair))
        best = accuracy if best is None else max(best, accuracy)
    return best
