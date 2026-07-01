"""Shared domain artifacts — the lowest layer.

Both ``tymi.core`` and ``tymi.ports`` depend on these types; the artifacts
depend on nothing internal. Keeping them here (rather than under ``tymi.core``)
lets ports reference domain types without importing the core, so the
core → ports → domain layering stays acyclic (AD-1, AD-10).
"""
