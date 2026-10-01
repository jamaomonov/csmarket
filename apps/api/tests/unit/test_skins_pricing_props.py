"""Properties of ``quote`` and ``to_uzs`` under the launch rules (spec §14)."""

from __future__ import annotations

from decimal import Decimal

from csmarket.modules.skins.pricing import DEFAULT_RULES, quote, to_uzs
from hypothesis import given
from hypothesis import strategies as st

costs = st.integers(min_value=1, max_value=50_000_000)  # $0.001 .. $50 000
counts = st.one_of(st.none(), st.integers(min_value=0, max_value=5000))
cats = st.sampled_from(["rifles", "knives", "stickers", "cases"])


@given(cost=costs, count=counts, cat=cats)
def test_price_covers_cost_plus_min_margin_and_floor(
    cost: int, count: int | None, cat: str
) -> None:
    q = quote(cost, rules=DEFAULT_RULES, category=cat, count_auto=count)
    assert q.price_usd >= q.cost_usd + DEFAULT_RULES.min_margin_usd - Decimal("0.01")
    assert q.price_usd >= DEFAULT_RULES.price_floor_usd
    assert q.price_usd == q.price_usd.quantize(Decimal("0.01"))


@given(a=costs, b=costs, count=counts)
def test_price_never_falls_when_cost_rises(a: int, b: int, count: int | None) -> None:
    lo, hi = sorted((a, b))
    p_lo = quote(lo, rules=DEFAULT_RULES, category="rifles", count_auto=count).price_usd
    p_hi = quote(hi, rules=DEFAULT_RULES, category="rifles", count_auto=count).price_usd
    assert p_hi >= p_lo


@given(
    usd=st.decimals(min_value=Decimal("0.10"), max_value=Decimal("100000"), places=2),
    rate=st.decimals(min_value=Decimal("8000"), max_value=Decimal("20000"), places=4),
)
def test_uzs_rounds_up_to_a_hundred(usd: Decimal, rate: Decimal) -> None:
    uzs = to_uzs(usd, rate, round_to=100)
    assert uzs % 100 == 0
    assert uzs >= usd * rate
    assert uzs - usd * rate < 100
