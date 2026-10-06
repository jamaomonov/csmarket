"""The cost a price is built from: the cheaper source, or the one with stock."""

from __future__ import annotations

from csmarket.modules.skins.repricing import cost_units


def test_cost_is_the_cheaper_source_or_the_one_present() -> None:
    assert cost_units(12_345, 11_000) == 11_000
    assert cost_units(12_345, None) == 12_345
    assert cost_units(None, 9_000) == 9_000
    assert cost_units(None, None) is None
