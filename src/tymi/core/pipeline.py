"""Pipeline orchestrator (AD-8).

One linear flow, run in the core:
``Connect -> Profile -> Generate(Faithful | Chaos) -> LeakageGate -> Evaluate -> Export``.
Driving adapters (CLI, UI) only build a ``Config`` and invoke ``run``.

This is a skeleton for the scaffold story; stages are implemented in later
stories.
"""

from __future__ import annotations

import numpy as np


class Orchestrator:
    """Runs the pipeline stages over immutable artifacts."""

    def run(self, config: object, rng: np.random.Generator) -> None:
        """Execute the pipeline. Not implemented until stage stories land."""
        raise NotImplementedError(
            "Pipeline stages are implemented in later stories (Epics 1-5)."
        )
