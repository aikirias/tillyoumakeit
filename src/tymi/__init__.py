"""TYMI — Fake It Till You Make It.

Faithful synthetic data generator + data chaos monkey. Hexagonal core: the
domain (`tymi.core`) depends only on abstract ports (`tymi.ports`); all I/O
lives in adapters discovered as plugins.
"""

__version__ = "0.0.1"
