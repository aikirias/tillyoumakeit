"""Domain core: pipeline orchestration, artifacts, RNG, plugin registry, errors.

AD-1: this package must import only ``tymi.ports`` (plus stdlib/third-party),
never a concrete adapter package. Enforced by the import-linter contract.
"""
