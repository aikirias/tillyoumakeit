"""Chaos Policy application (Story 3.5).

Turns a declarative :class:`~tymi.config.models.ChaosConfig` into a run over a
generated ``Dataset``:

- **mixed** — corrupt a ``rate`` fraction of rows and leave the rest faithful. Exactly
  ``round(rate·n)`` rows are selected and the mutator chain is applied to that
  sub-frame (each mutator corrupts all of it), so the realised fraction of corrupted
  rows matches ``rate`` within the ±2 pp acceptance margin. Structural (schema-changing)
  mutators cannot run in mixed mode — a per-row schema change is meaningless.
- **fully_chaotic** — corrupt the whole table. Over a table with foreign keys this
  breaks referential integrity by design, so it requires explicit confirmation.

The chain is resolved from the ``tymi.mutators`` entry points (AD-3); each mutator is
built with its policy params (AD-5). Deterministic for a given seed (AD-4/AD-11).
"""

from __future__ import annotations

import numpy as np

from tymi.chaos.engine import apply_chaos
from tymi.config.models import ChaosConfig, MutatorSpec
from tymi.core.errors import ChaosError
from tymi.core.plugins import load_mutators
from tymi.domain.artifacts import Dataset, FaultManifest
from tymi.ports import Mutator


def resolve_policy(
    specs: list[MutatorSpec],
    *,
    registry: dict[str, object] | None = None,
    proportion: float | None = None,
) -> list[Mutator]:
    """Build the mutator chain from ``specs`` (name + params) via the registry (AD-3)."""
    available = dict(load_mutators() if registry is None else registry)
    mutators: list[Mutator] = []
    for spec in specs:
        factory = available.get(spec.name)
        if factory is None:
            raise ChaosError(f"unknown mutator {spec.name!r}; registered: {sorted(available)}")
        params = dict(spec.params)
        if proportion is not None:
            params["proportion"] = proportion
        try:
            mutator = factory(**params)
        except ChaosError:
            raise
        except Exception as exc:  # noqa: BLE001 - bad policy params must not leak a raw error
            raise ChaosError(f"invalid params for mutator {spec.name!r}: {exc}") from exc
        if not isinstance(mutator, Mutator):
            raise ChaosError(f"mutator {spec.name!r} does not satisfy the Mutator port")
        mutators.append(mutator)
    return mutators


def apply_policy(
    dataset: Dataset,
    config: ChaosConfig,
    *,
    rng: np.random.Generator,
    confirmed: bool = False,
    registry: dict[str, object] | None = None,
) -> tuple[Dataset, FaultManifest]:
    """Apply the Chaos Policy to ``dataset`` per its ``mode`` (Story 3.5)."""
    # rate governs how much is corrupted; every targeted cell in scope is corrupted.
    mutators = resolve_policy(config.mutators, registry=registry, proportion=1.0)

    if config.mode == "fully_chaotic":
        if dataset.schema.foreign_keys and not confirmed:
            raise ChaosError(
                "fully_chaotic mode over a table with foreign keys breaks referential "
                "integrity by design; re-run with explicit confirmation (--confirm)."
            )
        return apply_chaos(dataset, mutators, rng=rng)

    # mixed
    structural = [m.name for m in mutators if getattr(m, "structural", False)]
    if structural:
        raise ChaosError(
            f"structural mutators {structural} cannot run in mixed mode (a per-row schema "
            "change is meaningless); use fully_chaotic mode."
        )
    n = len(dataset.frame)
    if n == 0 or not mutators:
        return dataset, FaultManifest()
    # Corrupt the whole table first (proportion forced to 1.0), then keep only a
    # ``rate`` fraction of the rows that were ACTUALLY corrupted, reverting the rest.
    # Selecting from the genuinely-corrupted set means the realised fraction hits the
    # target even when a targeted column is largely null (blind row selection would
    # miss the null cells and drift below rate).
    fully, manifest = apply_chaos(dataset, mutators, rng=rng)
    corrupted = sorted({int(e["row"]) for e in manifest.entries if "row" in e})
    if not corrupted:
        return dataset, FaultManifest()
    k = round(config.rate * n)
    if k == 0:
        k = 1  # a positive rate on a non-empty corruptable frame corrupts >= 1 row
    keep = (
        set(corrupted)
        if len(corrupted) <= k
        else set(int(p) for p in rng.choice(np.array(corrupted), size=k, replace=False))
    )

    new_frame = dataset.frame.copy()
    touched = {e["column"] for e in manifest.entries if e.get("row") in keep and "column" in e}
    keep_pos = sorted(keep)
    for col in touched:
        col_idx = new_frame.columns.get_loc(col)
        if fully.frame[col].dtype == object:  # only degrade dtype when the fault requires it
            new_frame[col] = new_frame[col].astype(object)
        new_frame.iloc[keep_pos, col_idx] = fully.frame[col].iloc[keep_pos].to_numpy()
    kept_entries = [e for e in manifest.entries if e.get("row") in keep]
    return Dataset(frame=new_frame, schema=dataset.schema), FaultManifest(entries=kept_entries)
