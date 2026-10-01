"""Shared kernel — utilities and infrastructure used by every module.

Nothing in ``core`` may import from ``csmarket.modules``. Direction is one-way:
modules depend on core, never the reverse.
"""
