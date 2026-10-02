"""``orders.buying.attempt_buy``: one order, one purchase at Waxpeer (rulings R3, R4, R6).

Lookup first and never rebuy; one substitute within the ceiling; 403 and 429 keep the order
in flight; a lost answer or a 5xx is resolved by lookup; low balance, sold out and a broken
trade link are refunded to the balance. A scripted Waxpeer stands in; the database is real.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from csmarket.core import clock
from csmarket.core.config import Settings, get_settings
from csmarket.core.errors import ConflictError
from csmarket.core.ids import new_id
from csmarket.modules.orders.api import Order, SkinTrade, attempt_buy
from csmarket.modules.skins.api import (
    SkinItem,
    WaxpeerBuy,
    WaxpeerBuyRefusedError,
    WaxpeerError,
    WaxpeerForbiddenError,
    WaxpeerRateLimitedError,
    WaxpeerUnavailableError,
)
from csmarket.modules.wallet.api import user_balance
from prometheus_client import REGISTRY
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.fake_trade_client import FakeTradeClient, waxpeer_trade
from tests.integration.orders_factory import (
    build_order,
    make_due,
    make_item_and_rate,
    make_order,
    make_trade,
)
from tests.integration.payments_factory import make_user

PRICE = Decimal(171_800)
COST = 12_345  # orders_factory's cost_units; the ceiling is 12_345 × 1.03 → 12_715
SOLD = WaxpeerBuyRefusedError("Item not found", new_price_units=None)


@pytest.fixture
def settings() -> Settings:
    """Live listings allowed (a key is set; the fake answers instead of Waxpeer)."""
    return get_settings().model_copy(update={"waxpeer_api_key": "test-key-not-real"})


@pytest.fixture
def fake() -> FakeTradeClient:
    return FakeTradeClient()


async def _buying(db: AsyncSession, **overrides: object) -> Order:
    """A kassa-paid order in ``buying`` with its trade waiting to be bought."""
    values: dict[str, Any] = {
        "status": "buying",
        "paid_with": "payme",
        "paid_at": clock.now(),
        "price_uzs": PRICE,
    }
    values.update(overrides)
    order = await make_order(db, **values)
    await make_trade(db, order, buy_pending=True)
    return order


@pytest.fixture
async def buying_order(db_session: AsyncSession) -> Order:
    return await _buying(db_session)


async def load(db: AsyncSession, order: Order) -> tuple[Order, SkinTrade]:
    """The order and its trade as committed."""
    row = await db.scalar(
        select(Order).where(Order.id == order.id).execution_options(populate_existing=True)
    )
    trade = await db.scalar(
        select(SkinTrade)
        .where(SkinTrade.order_id == order.id)
        .execution_options(populate_existing=True)
    )
    assert row is not None
    assert trade is not None
    return row, trade


def metric(outcome: str) -> float:
    value = REGISTRY.get_sample_value("csmarket_order_buys_total", {"outcome": outcome})
    return value or 0.0


async def _attempt(
    db: AsyncSession, fake: FakeTradeClient, order: Order, settings: Settings
) -> str:
    return await attempt_buy(db, fake, order_id=order.id, settings=settings)


# --- the happy path and adoption ----------------------------------------------------------


async def test_buys_the_chosen_listing_at_the_paid_units(
    db_session: AsyncSession, buying_order: Order, fake: FakeTradeClient, settings: Settings
) -> None:
    before = metric("bought")
    assert await _attempt(db_session, fake, buying_order, settings) == "bought"
    assert fake.lookup_calls == 1
    assert fake.bought == [(buying_order.listing_id, COST, buying_order.id)]
    order, trade = await load(db_session, buying_order)
    assert order.status == "buying"
    assert order.refunded_at is None
    assert (trade.waxpeer_id, trade.bought_units, trade.status) == (50_000_002, COST, 0)
    assert trade.buy_pending is False
    assert order.next_check_at is not None
    assert order.next_check_at <= clock.now()
    assert metric("bought") == before + 1


async def test_a_found_trade_is_adopted_never_rebought(
    db_session: AsyncSession, buying_order: Order, fake: FakeTradeClient, settings: Settings
) -> None:
    fake.lookup_returns([waxpeer_trade(buying_order.id, status=2)])
    fake.buy_raises(AssertionError("must not buy"))
    assert await _attempt(db_session, fake, buying_order, settings) == "adopted"
    assert fake.buy_calls == 0
    _, trade = await load(db_session, buying_order)
    assert (trade.status, trade.waxpeer_id, trade.trade_id) == (2, 40_100_200, "7700112233")
    assert trade.bought_units == 12_345
    assert trade.seller["name"] == "redrawn_seller"
    assert trade.buy_pending is False


async def test_two_live_trades_on_the_first_lookup_buy_nothing(
    db_session: AsyncSession, buying_order: Order, fake: FakeTradeClient, settings: Settings
) -> None:
    fake.lookup_returns(
        [waxpeer_trade(buying_order.id, status=2), waxpeer_trade(buying_order.id, id=2, status=4)]
    )
    assert await _attempt(db_session, fake, buying_order, settings) == "ambiguous"
    assert fake.buy_calls == 0
    order, trade = await load(db_session, buying_order)
    assert trade.attention_reason == "ambiguous_trade"
    assert trade.buy_pending is False
    assert order.status == "buying"
    assert order.refunded_at is None


@pytest.mark.parametrize(
    "error",
    [
        WaxpeerUnavailableError("timeout"),
        WaxpeerRateLimitedError("slow", retry_after_seconds=1),
        WaxpeerError("no", status=200),
    ],
)
async def test_a_failed_first_lookup_defers_the_buy(
    db_session: AsyncSession,
    buying_order: Order,
    fake: FakeTradeClient,
    settings: Settings,
    error: Exception,
) -> None:
    fake.lookup_raises(error)
    assert await _attempt(db_session, fake, buying_order, settings) == "lookup_later"
    assert fake.buy_calls == 0
    order, trade = await load(db_session, buying_order)
    assert trade.buy_pending is True
    assert trade.buy_unconfirmed_at is None
    # A failed lookup backs off (minor 3): the next tick does not ask again at once.
    assert order.next_check_at is not None
    left = order.next_check_at - clock.now()
    assert timedelta(seconds=15) < left <= timedelta(seconds=20)
    assert await _attempt(db_session, fake, buying_order, settings) == "nothing_to_do"
    assert fake.lookup_calls == 1
    await make_due(db_session, buying_order)
    fake.lookup_returns([])
    assert await _attempt(db_session, fake, buying_order, settings) == "bought"


@pytest.mark.parametrize(
    ("retry_after", "waits"),
    [(1, 20), (45, 45), (3600, 300)],
    ids=["shorter_hint", "longer_hint", "capped"],
)
@pytest.mark.parametrize("where", ["lookup", "buy"])
async def test_a_429_waits_as_long_as_waxpeer_asks(
    *,
    db_session: AsyncSession,
    buying_order: Order,
    fake: FakeTradeClient,
    settings: Settings,
    retry_after: int,
    waits: int,
    where: str,
) -> None:
    limited = WaxpeerRateLimitedError("slow", retry_after_seconds=retry_after)
    if where == "lookup":
        fake.lookup_raises(limited)
    else:
        fake.buy_raises(limited)
    outcome = await _attempt(db_session, fake, buying_order, settings)
    assert outcome == ("lookup_later" if where == "lookup" else "rate_limited")
    order, _ = await load(db_session, buying_order)
    assert order.next_check_at is not None
    left = order.next_check_at - clock.now()
    assert timedelta(seconds=waits - 5) < left <= timedelta(seconds=waits)


async def test_nothing_to_do_unless_buying_with_a_buy_pending(
    db_session: AsyncSession, fake: FakeTradeClient, settings: Settings
) -> None:
    paid = await make_order(db_session, status="paid", paid_with="payme")
    settled = await _buying(db_session)
    _, trade = await load(db_session, settled)
    trade.buy_pending = False
    await db_session.commit()
    for order in (paid, settled):
        assert await _attempt(db_session, fake, order, settings) == "nothing_to_do"
    unknown = await attempt_buy(db_session, fake, order_id=new_id(), settings=settings)
    assert unknown == "nothing_to_do"
    assert fake.lookup_calls == 0


async def test_a_second_attempt_while_one_holds_the_order_does_nothing(
    db_session: AsyncSession, fake: FakeTradeClient, settings: Settings
) -> None:
    order = await _buying(db_session, next_check_at=clock.now() + timedelta(minutes=4))
    assert await _attempt(db_session, fake, order, settings) == "nothing_to_do"
    assert fake.lookup_calls == 0


# --- lost answers, 5xx, 403, 429 -----------------------------------------------------------


async def test_lost_answer_is_resolved_by_lookup_never_rebought(
    db_session: AsyncSession, buying_order: Order, fake: FakeTradeClient, settings: Settings
) -> None:
    fake.buy_raises(WaxpeerUnavailableError("timeout"))
    assert await _attempt(db_session, fake, buying_order, settings) == "unconfirmed"
    fake.buy_raises(AssertionError("must not buy again"))
    assert await _attempt(db_session, fake, buying_order, settings) == "nothing_to_do"
    assert fake.buy_calls == 1  # Task 9's sweep adopts it by lookup
    order, trade = await load(db_session, buying_order)
    assert trade.buy_unconfirmed_at is not None
    assert trade.buy_pending is False
    assert order.status == "buying"
    assert order.refunded_at is None


async def test_a_5xx_on_the_buy_is_unconfirmed_never_substituted(
    db_session: AsyncSession, buying_order: Order, fake: FakeTradeClient, settings: Settings
) -> None:
    fake.buy_raises(WaxpeerError("bad gateway", status=502))
    fake.listings(buying_order.market_hash_name, [(777, 12_000)])
    before = metric("unconfirmed")
    assert await _attempt(db_session, fake, buying_order, settings) == "unconfirmed"
    assert (fake.buy_calls, fake.search_calls, fake.balance_calls) == (1, 0, 0)
    order, trade = await load(db_session, buying_order)
    assert trade.buy_unconfirmed_at is not None
    assert order.refunded_at is None
    assert metric("unconfirmed") == before + 1


async def test_forbidden_buy_keeps_order_buying_and_alerts(
    db_session: AsyncSession, buying_order: Order, fake: FakeTradeClient, settings: Settings
) -> None:
    fake.lookup_returns([])
    fake.buy_raises(WaxpeerForbiddenError("whitelist"))
    fake.listings(buying_order.market_hash_name, [(777, 12_000)])
    before = metric("forbidden")
    assert await _attempt(db_session, fake, buying_order, settings) == "forbidden"
    order, trade = await load(db_session, buying_order)
    assert order.status == "buying"
    assert order.refunded_at is None
    assert trade.attention_reason == "waxpeer_forbidden"
    assert trade.buy_pending
    assert fake.search_calls == 0  # no substitute
    assert metric("forbidden") == before + 1
    assert order.next_check_at is not None
    left = order.next_check_at - clock.now()
    assert timedelta(seconds=55) < left <= timedelta(seconds=60)  # backoff, not every tick
    assert await _attempt(db_session, fake, buying_order, settings) == "nothing_to_do"


async def test_a_forbidden_lookup_buys_nothing_and_alerts(
    db_session: AsyncSession, buying_order: Order, fake: FakeTradeClient, settings: Settings
) -> None:
    fake.lookup_raises(WaxpeerForbiddenError())
    assert await _attempt(db_session, fake, buying_order, settings) == "forbidden"
    assert fake.buy_calls == 0
    _, trade = await load(db_session, buying_order)
    assert trade.attention_reason == "waxpeer_forbidden"
    assert trade.buy_pending


async def test_a_buy_after_access_returns_clears_the_forbidden_attention(
    db_session: AsyncSession, buying_order: Order, fake: FakeTradeClient, settings: Settings
) -> None:
    fake.buy_raises(WaxpeerForbiddenError())
    assert await _attempt(db_session, fake, buying_order, settings) == "forbidden"
    await make_due(db_session, buying_order)
    assert await _attempt(db_session, fake, buying_order, settings) == "forbidden"
    await make_due(db_session, buying_order)
    _, trade = await load(db_session, buying_order)
    trade.resolved_at, trade.resolved_by = clock.now(), "admin:x"  # an operator looked
    await db_session.commit()
    fake.buy_returns(WaxpeerBuy(id=6, price_units=COST))
    assert await _attempt(db_session, fake, buying_order, settings) == "bought"
    _, trade = await load(db_session, buying_order)
    assert trade.attention_reason is None
    assert trade.resolved_at is None


async def test_rate_limited_buy_is_retried(
    db_session: AsyncSession, buying_order: Order, fake: FakeTradeClient, settings: Settings
) -> None:
    fake.lookup_returns([])
    fake.buy_raises(WaxpeerRateLimitedError("slow", retry_after_seconds=1))
    assert await _attempt(db_session, fake, buying_order, settings) == "rate_limited"
    order, trade = await load(db_session, buying_order)
    assert trade.buy_pending
    assert trade.attention_reason is None
    assert order.next_check_at is not None
    left = order.next_check_at - clock.now()
    assert timedelta(seconds=15) < left <= timedelta(seconds=20)
    assert await _attempt(db_session, fake, buying_order, settings) == "nothing_to_do"
    await make_due(db_session, buying_order)
    fake.buy_returns(WaxpeerBuy(id=6, price_units=10_000))
    assert await _attempt(db_session, fake, buying_order, settings) == "bought"
    _, trade = await load(db_session, buying_order)
    assert (trade.waxpeer_id, trade.bought_units) == (6, 10_000)


# --- substitutes, sold out, low balance, a broken link -------------------------------------


async def test_a_sold_listing_is_replaced_by_one_within_the_ceiling(
    db_session: AsyncSession, buying_order: Order, fake: FakeTradeClient, settings: Settings
) -> None:
    fake.refuse(buying_order.listing_id, SOLD)
    fake.listings(
        buying_order.market_hash_name,
        [(222, 12_716), (333, 12_715)],  # just over the ceiling: skipped; at it: bought
        manual=[(444, 11_000)],  # a manual seller: never
    )
    assert await _attempt(db_session, fake, buying_order, settings) == "bought"
    assert fake.bought == [(333, 12_715, buying_order.id)]
    order, trade = await load(db_session, buying_order)
    assert (trade.listing_id, trade.paid_units, trade.bought_units) == (333, 12_715, 12_715)
    assert order.listing_id == buying_order.listing_id  # the buyer's choice stays on record


async def test_a_substitute_above_the_ceiling_is_never_bought(
    db_session: AsyncSession, buying_order: Order, fake: FakeTradeClient, settings: Settings
) -> None:
    fake.refuse(buying_order.listing_id, SOLD)
    fake.listings(buying_order.market_hash_name, [(222, 12_716)])
    before = metric("sold_out")
    assert await _attempt(db_session, fake, buying_order, settings) == "sold_out"
    assert fake.bought == []
    order, trade = await load(db_session, buying_order)
    assert (order.status, order.failure_reason, order.refunded_to) == (
        "failed",
        "sold_out",
        "balance",
    )
    assert trade.buy_pending is False
    assert await user_balance(db_session, order.user_id) == PRICE
    assert metric("sold_out") == before + 1


async def test_only_one_substitute_is_tried(
    db_session: AsyncSession, buying_order: Order, fake: FakeTradeClient, settings: Settings
) -> None:
    fake.refuse(buying_order.listing_id, SOLD)
    fake.refuse(333, SOLD)
    fake.listings(buying_order.market_hash_name, [(333, 12_000), (334, 12_100)])
    assert await _attempt(db_session, fake, buying_order, settings) == "sold_out"
    assert fake.buy_calls == 2
    order, _ = await load(db_session, buying_order)
    assert order.status == "failed"
    assert order.failure_reason == "sold_out"


async def test_a_moved_price_is_never_accepted_blindly(
    db_session: AsyncSession, buying_order: Order, fake: FakeTradeClient, settings: Settings
) -> None:
    fake.refuse(buying_order.listing_id, WaxpeerBuyRefusedError("price", new_price_units=12_400))
    assert await _attempt(db_session, fake, buying_order, settings) == "sold_out"
    assert fake.buy_calls == 1


async def test_a_4xx_on_the_buy_means_nothing_was_bought(
    db_session: AsyncSession, buying_order: Order, fake: FakeTradeClient, settings: Settings
) -> None:
    fake.buy_raises(WaxpeerError("bad request", status=400))
    assert await _attempt(db_session, fake, buying_order, settings) == "sold_out"
    order, _ = await load(db_session, buying_order)
    assert order.status == "failed"
    assert order.refunded_at is not None


async def test_a_doppler_is_substituted_under_waxpeers_spelling(
    db_session: AsyncSession, fake: FakeTradeClient, settings: Settings
) -> None:
    _, fx = await make_item_and_rate(db_session)
    item = SkinItem(
        id=new_id(),
        market_hash_name="★ Karambit | Doppler (Factory New)",
        phase="Phase 2",
        slug=f"karambit-doppler-p2-{new_id()[-6:]}",
        category="knives",
        search_text="karambit doppler",
    )
    db_session.add(item)
    await db_session.commit()
    user = await make_user(db_session)
    order = await build_order(
        db_session, user=user, item=item, fx=fx, status="buying", paid_with="payme"
    )
    await db_session.commit()
    await make_trade(db_session, order, buy_pending=True)
    fake.refuse(order.listing_id, SOLD)
    fake.listings("★ Karambit | Doppler Phase 2 (Factory New)", [(555, 12_000)])
    assert await _attempt(db_session, fake, order, settings) == "bought"
    assert fake.bought == [(555, 12_000, order.id)]


async def test_low_balance_by_message_is_refunded_at_once(
    db_session: AsyncSession, buying_order: Order, fake: FakeTradeClient, settings: Settings
) -> None:
    fake.buy_raises(WaxpeerBuyRefusedError("Not enough balance", new_price_units=None))
    fake.listings(buying_order.market_hash_name, [(777, 12_000)])
    before = metric("low_balance")
    assert await _attempt(db_session, fake, buying_order, settings) == "low_balance"
    assert (fake.search_calls, fake.balance_calls) == (0, 0)
    order, trade = await load(db_session, buying_order)
    assert (order.status, order.failure_reason) == ("failed", "waxpeer_low_balance")
    assert trade.buy_pending is False
    assert await user_balance(db_session, order.user_id) == PRICE
    assert metric("low_balance") == before + 1


async def test_low_balance_by_our_waxpeer_wallet_is_refunded(
    db_session: AsyncSession, buying_order: Order, fake: FakeTradeClient, settings: Settings
) -> None:
    fake.buy_raises(WaxpeerError("Something went wrong", status=200, body="insufficient"))
    fake.balance_returns(COST - 1)
    assert await _attempt(db_session, fake, buying_order, settings) == "low_balance"
    order, _ = await load(db_session, buying_order)
    assert order.failure_reason == "waxpeer_low_balance"


async def test_a_failing_balance_call_does_not_read_as_low(
    db_session: AsyncSession, buying_order: Order, fake: FakeTradeClient, settings: Settings
) -> None:
    fake.refuse(buying_order.listing_id, SOLD)
    fake.balance_raises(WaxpeerUnavailableError("down"))
    assert await _attempt(db_session, fake, buying_order, settings) == "sold_out"
    order, _ = await load(db_session, buying_order)
    assert order.failure_reason == "sold_out"


async def test_a_broken_trade_link_is_refunded_without_calling_waxpeer(
    db_session: AsyncSession, fake: FakeTradeClient, settings: Settings
) -> None:
    order = await _buying(db_session, trade_link="nope")
    before = metric("invalid_link")
    assert await _attempt(db_session, fake, order, settings) == "invalid_link"
    assert fake.lookup_calls == 0
    assert fake.buy_calls == 0
    row, trade = await load(db_session, order)
    assert (row.status, row.failure_reason, row.refunded_to) == (
        "failed",
        "invalid_trade_link",
        "balance",
    )
    assert trade.buy_pending is False
    assert metric("invalid_link") == before + 1


@pytest.mark.parametrize(
    "refusal",
    [
        WaxpeerBuyRefusedError("Invalid tradelink", new_price_units=None),
        WaxpeerBuyRefusedError("Inventory is private", new_price_units=None),
        WaxpeerError("User has a trade ban", status=400, body="{}"),
    ],
    ids=["invalid", "private", "trade_ban"],
)
async def test_a_refusal_naming_the_trade_link_is_refunded_as_such(
    db_session: AsyncSession,
    buying_order: Order,
    fake: FakeTradeClient,
    settings: Settings,
    refusal: WaxpeerError,
) -> None:
    """Another listing would refuse the same link: no substitute, no «sold out» — the buyer
    is told the link did not work (final review minor 1)."""
    fake.buy_raises(refusal)
    fake.listings(buying_order.market_hash_name, [(777, 12_000)])
    before = metric("invalid_link")
    assert await _attempt(db_session, fake, buying_order, settings) == "invalid_link"
    assert (fake.buy_calls, fake.search_calls, fake.balance_calls) == (1, 0, 0)
    order, trade = await load(db_session, buying_order)
    assert (order.status, order.failure_reason, order.refunded_to) == (
        "failed",
        "invalid_trade_link",
        "balance",
    )
    assert trade.buy_pending is False
    assert await user_balance(db_session, order.user_id) == PRICE
    assert metric("invalid_link") == before + 1


async def test_a_body_that_echoes_the_link_is_not_a_link_refusal(
    db_session: AsyncSession, buying_order: Order, fake: FakeTradeClient, settings: Settings
) -> None:
    fake.refuse(
        buying_order.listing_id,
        WaxpeerBuyRefusedError(
            "Item not found", new_price_units=None, body='{"tradelink": "redrawn"}'
        ),
    )
    assert await _attempt(db_session, fake, buying_order, settings) == "sold_out"


# --- a write after someone else moved the rows ---------------------------------------------


async def test_a_buy_the_sweep_already_recorded_is_the_same_purchase(
    db_session: AsyncSession, buying_order: Order, fake: FakeTradeClient, settings: Settings
) -> None:
    async def adopted_meanwhile() -> None:
        _, trade = await load(db_session, buying_order)
        trade.buy_pending, trade.waxpeer_id = False, 50_000_002  # the id this buy returns
        await db_session.commit()

    fake.before_buy = adopted_meanwhile
    bought, adopted = metric("bought"), metric("adopted")
    assert await _attempt(db_session, fake, buying_order, settings) == "adopted"
    _, trade = await load(db_session, buying_order)
    assert trade.attention_reason is None
    # One purchase, counted once: the sweep's adoption is what recorded it (minor 7).
    assert (metric("bought"), metric("adopted")) == (bought, adopted + 1)


async def test_a_buy_landing_on_moved_rows_is_flagged_never_silent(
    db_session: AsyncSession, buying_order: Order, fake: FakeTradeClient, settings: Settings
) -> None:
    async def adopted_meanwhile() -> None:
        _, trade = await load(db_session, buying_order)
        trade.buy_pending, trade.waxpeer_id = False, 999
        await db_session.commit()

    fake.before_buy = adopted_meanwhile
    before = metric("stale_bought")
    assert await _attempt(db_session, fake, buying_order, settings) == "stale_bought"
    _, trade = await load(db_session, buying_order)
    assert (trade.waxpeer_id, trade.bought_units) == (999, None)
    assert trade.attention_reason == "ambiguous_trade"
    assert trade.resolved_at is None
    assert metric("stale_bought") == before + 1


async def test_a_refusal_after_the_order_left_buying_refunds_nothing(
    db_session: AsyncSession, buying_order: Order, fake: FakeTradeClient, settings: Settings
) -> None:
    async def delivered_meanwhile() -> None:
        order, _ = await load(db_session, buying_order)
        order.status = "delivered"
        await db_session.commit()

    fake.before_buy = delivered_meanwhile
    fake.buy_raises(SOLD)
    assert await _attempt(db_session, fake, buying_order, settings) == "nothing_to_do"
    order, _ = await load(db_session, buying_order)
    assert order.status == "delivered"
    assert order.refunded_at is None


@pytest.mark.parametrize(
    "case",
    [
        ("before_lookup", "adopt"),
        ("before_buy", "forbidden"),
    ],
)
async def test_no_write_lands_on_an_order_that_left_buying_meanwhile(
    db_session: AsyncSession,
    buying_order: Order,
    fake: FakeTradeClient,
    settings: Settings,
    case: tuple[str, str],
) -> None:
    hook, script = case

    async def delivered_meanwhile() -> None:
        order, _ = await load(db_session, buying_order)
        order.status = "delivered"
        await db_session.commit()

    setattr(fake, hook, delivered_meanwhile)
    if script == "adopt":
        fake.lookup_returns([waxpeer_trade(buying_order.id, status=4)])
    else:
        fake.buy_raises(WaxpeerForbiddenError())
    assert await _attempt(db_session, fake, buying_order, settings) == "nothing_to_do"
    _, trade = await load(db_session, buying_order)
    assert trade.buy_pending is True
    assert trade.waxpeer_id is None
    assert trade.attention_reason is None
    assert trade.buy_unconfirmed_at is None


async def test_a_lost_answer_on_an_order_that_left_buying_is_flagged(
    db_session: AsyncSession, buying_order: Order, fake: FakeTradeClient, settings: Settings
) -> None:
    async def delivered_meanwhile() -> None:
        order, _ = await load(db_session, buying_order)
        order.status = "delivered"
        await db_session.commit()

    fake.before_buy = delivered_meanwhile
    fake.buy_raises(WaxpeerUnavailableError("timeout"))
    assert await _attempt(db_session, fake, buying_order, settings) == "stale_bought"
    _, trade = await load(db_session, buying_order)
    assert trade.attention_reason == "ambiguous_trade"


async def test_a_refund_that_cannot_be_booked_writes_nothing(
    db_session: AsyncSession, fake: FakeTradeClient, settings: Settings
) -> None:
    order = await _buying(db_session, trade_link="nope", paid_with=None)
    order_id = order.id  # the rollback expires ``order`` in this shared session
    with pytest.raises(ConflictError):
        await attempt_buy(db_session, fake, order_id=order_id, settings=settings)
    row = await db_session.get(Order, order_id)
    trade = await db_session.get(SkinTrade, order_id)
    assert row is not None
    assert trade is not None
    assert row.status == "buying"
    assert trade.buy_pending is True
