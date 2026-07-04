"""Chaos engine — resolve + run a chain of Mutators (Story 3.1).

The engine discovers Mutators from the ``tymi.mutators`` entry-point group (AD-3) by
name and runs them in the order the ``ChaosConfig`` declares, threading the one
injected ``numpy.random.Generator`` (AD-4/AD-11) and the mutated ``Dataset`` through
the chain, then merges each Mutator's ``FaultManifest`` into one auditable record.

It never imports a concrete Mutator, so a new fault family (Stories 3.2–3.4) runs by
registering an entry point alone — no engine change. Fault mutators themselves are
those later stories; this module is the engine + discovery + manifest merge.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np

from tymi.core.errors import ChaosError
from tymi.core.plugins import load_mutators
from tymi.domain.artifacts import Dataset, FaultManifest, merge_fault_manifests
from tymi.ports import Mutator


def resolve_mutators(
    names: Sequence[str], *, registry: Mapping[str, object] | None = None
) -> list[Mutator]:
    """Resolve mutator ``names`` to instances via the ``tymi.mutators`` registry.

    ``registry`` maps a name to a Mutator class/factory (defaults to
    :func:`~tymi.core.plugins.load_mutators`). Each entry is instantiated with no
    arguments. An unknown name raises :class:`ChaosError` (never a bare ``KeyError``);
    the returned order matches ``names`` exactly (AC-2).
    """
    available = dict(load_mutators() if registry is None else registry)
    resolved: list[Mutator] = []
    for name in names:
        factory = available.get(name)
        if factory is None:
            raise ChaosError(
                f"unknown mutator {name!r}; registered: {sorted(available)}"
            )
        try:
            mutator = factory()
        except ChaosError:
            raise
        except Exception as exc:  # noqa: BLE001 - a bad registry entry must not leak a raw error
            raise ChaosError(f"mutator {name!r} could not be instantiated: {exc}") from exc
        if not isinstance(mutator, Mutator):
            raise ChaosError(
                f"mutator {name!r} does not satisfy the Mutator port "
                "(needs a 'name' and an 'apply(dataset, *, rng)')."
            )
        resolved.append(mutator)
    return resolved


def apply_chaos(
    dataset: Dataset, mutators: Sequence[Mutator], *, rng: np.random.Generator
) -> tuple[Dataset, FaultManifest]:
    """Run ``mutators`` in order over ``dataset``, threading ``rng``; merge manifests.

    Each Mutator receives the current (already-mutated) Dataset and the shared ``rng``,
    and returns ``(Dataset, FaultManifest)``; the next Mutator sees the new Dataset.
    The merged manifest preserves chain order so the audit contract (Story 3.6) can map
    every entry back to what produced it. Deterministic for a given seed + chain.

    The caller's Dataset is never mutated: the engine works on a copy of the frame, so
    even a (contract-violating) Mutator that edits in place cannot corrupt the input,
    and re-running is idempotent. A Mutator that returns anything other than a
    ``(Dataset, FaultManifest)`` pair raises :class:`ChaosError` naming it, rather than
    a cryptic unpack/attribute error deep in the chain.
    """
    if not mutators:
        return dataset, FaultManifest()
    current = Dataset(frame=dataset.frame.copy(), schema=dataset.schema)
    manifests: list[FaultManifest] = []
    for mutator in mutators:
        result = mutator.apply(current, rng=rng)
        if not (isinstance(result, tuple) and len(result) == 2):
            raise ChaosError(
                f"mutator {mutator.name!r} must return a (Dataset, FaultManifest) pair, "
                f"got {type(result).__name__}."
            )
        current, manifest = result
        if not isinstance(current, Dataset) or not isinstance(manifest, FaultManifest):
            raise ChaosError(
                f"mutator {mutator.name!r} returned "
                f"({type(current).__name__}, {type(manifest).__name__}), "
                "expected (Dataset, FaultManifest)."
            )
        manifests.append(manifest)
    return current, merge_fault_manifests(manifests)
