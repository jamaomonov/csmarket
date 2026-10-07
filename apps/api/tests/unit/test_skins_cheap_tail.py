"""The cheap tail (ADR-0015): under 1 $ of cost, stickers take +2 pp instead of +5 and the
thinnest liquidity band +1 instead of +3. From 1 $ up, not a cent changes."""

from __future__ import annotations

from decimal import Decimal

import pytest
from csmarket.modules.skins.pricing import DEFAULT_RULES, quote

#: The rules before the tail: what every price from 1 $ up must still equal.
BEFORE = DEFAULT_RULES.model_copy(update={"min_margin_usd": Decimal("0.03"), "cheap_tail": None})


def test_a_cheap_sticker_with_two_lots_takes_the_tail_markups() -> None:
    q = quote(260, rules=DEFAULT_RULES, category="stickers", count_auto=2)
    assert (q.category_pp, q.liquidity_pp) == (Decimal(2), Decimal(1))
    assert q.price_usd == Decimal("0.31")  # 0.26 × 1.16 = 0.3016 → 0.31
    assert quote(260, rules=BEFORE, category="stickers", count_auto=2).price_usd == Decimal(
        "0.32"
    )  # 0.26 × 1.21 = 0.3146


def test_a_liquid_cheap_weapon_does_not_move() -> None:
    """No tail markup applies to it. (Below ~0.25 $ the minimum margin binds, and there the
    2-cent minimum is the only change.)"""
    kw = {"category": "rifles", "weapon": "AK-47", "count_auto": 60}
    for cost in (300, 480, 750, 990):
        assert (
            quote(cost, rules=DEFAULT_RULES, **kw).price_usd  # type: ignore[arg-type]
            == quote(cost, rules=BEFORE, **kw).price_usd  # type: ignore[arg-type]
        )


def test_a_sticker_at_one_and_a_half_dollars_keeps_its_five_points() -> None:
    q = quote(1_500, rules=DEFAULT_RULES, category="stickers", count_auto=2)
    assert (q.category_pp, q.liquidity_pp) == (Decimal(5), Decimal(3))


def test_the_minimum_margin_is_two_cents() -> None:
    assert DEFAULT_RULES.min_margin_usd == Decimal("0.02")
    assert DEFAULT_RULES.price_floor_usd == Decimal("0.10")


#: 20 items across every bracket, category and liquidity band, all at or above 1 $.
FROM_ONE_DOLLAR = [
    (cost, category, weapon, count)
    for cost, category, weapon in (
        (1_000, "stickers", None),
        (1_010, "rifles", "AK-47"),
        (4_990, "stickers", None),
        (9_990, "pistols", "Glock-18"),
        (10_000, "knives", None),
        (54_300, "stickers", None),
        (99_990, "gloves", None),
        (100_000, "rifles", "AWP"),
        (999_990, "knives", None),
        (1_500_000, "stickers", None),
    )
    for count in (2, 60)
]


@pytest.mark.parametrize(("cost", "category", "weapon", "count"), FROM_ONE_DOLLAR)
def test_from_one_dollar_up_not_a_cent_changes(
    cost: int, category: str, weapon: str | None, count: int
) -> None:
    kw = {"category": category, "weapon": weapon, "count_auto": count}
    assert (
        quote(cost, rules=DEFAULT_RULES, **kw).price_usd  # type: ignore[arg-type]
        == quote(cost, rules=BEFORE, **kw).price_usd  # type: ignore[arg-type]
    )
