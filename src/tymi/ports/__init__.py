"""Ports: the abstract interfaces the domain core depends on (AD-1).

Adapters implement these structurally (``typing.Protocol``); they do not need to
inherit. Every stochastic method takes a keyword-only ``rng`` (AD-11).
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

import numpy as np

from tymi.domain.artifacts import Dataset, FaultManifest, Profile, Schema


@runtime_checkable
class EngineAdapter(Protocol):
    """A database engine as both source and destination (AD-2).

    ``supports_*`` advertise capabilities; the orchestrator validates a chosen
    source/destination against them before running.
    """

    supports_introspect: bool
    supports_sample: bool
    supports_write: bool

    def introspect(self, table: str) -> Schema: ...

    def sample(self, table: str, *, rows: int, rng: np.random.Generator) -> Dataset: ...

    def load(self, dataset: Dataset, *, table: str) -> None: ...


@runtime_checkable
class Synthesizer(Protocol):
    """Produces faithful synthetic data from a Profile."""

    def generate(self, profile: Profile, *, rows: int, rng: np.random.Generator) -> Dataset: ...


@runtime_checkable
class Mutator(Protocol):
    """Applies one fault type to a Dataset, recording what it corrupted."""

    name: str

    def apply(
        self, dataset: Dataset, *, rng: np.random.Generator
    ) -> tuple[Dataset, FaultManifest]: ...


@runtime_checkable
class PIIClassifier(Protocol):
    """Detects and tags sensitive columns in a Profile."""

    def classify(self, profile: Profile) -> Profile: ...


@runtime_checkable
class PrivacyFilter(Protocol):
    """Drops synthetic rows too close to real records (faithful output)."""

    def filter(self, dataset: Dataset, *, reference: Dataset) -> Dataset: ...


@runtime_checkable
class Evaluator(Protocol):
    """Evaluates a Dataset per run mode (AD-12)."""

    def evaluate(
        self, dataset: Dataset, *, run_mode: str, profile: Profile | None = None
    ) -> Any: ...


@runtime_checkable
class Exporter(Protocol):
    """Writes a Dataset to a destination, mapping from the canonical Schema."""

    def export(self, dataset: Dataset, *, target: str) -> None: ...


__all__ = [
    "EngineAdapter",
    "Synthesizer",
    "Mutator",
    "PIIClassifier",
    "PrivacyFilter",
    "Evaluator",
    "Exporter",
]
