"""``orders.lisskins_buying.attempt_lisskins_buy`` — spec 2026-10-07 §5 row by row.

Idempotent on our ``custom_id`` (LIS-SKINS refuses a known one); one substitute of any
source within the ceiling; a lost answer is settled by ``market/info``, never by buying
again blind; low balance, sold out and a broken trade link are refunded to the balance.
A scripted LIS-SKINS stands in; the database is real.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from decimal import Decimal

import pytest
from csmarket.core import clock
from csmarket.core.config import Settings, get_settings
from csmarket.modules.lisskins.api import (
    LisskinsError,
    LisskinsForbiddenError,
    LisskinsRateLimitedError,
    LisskinsUnavailableError,
    Purchase,
)
from csmarket.modules.lisskins.models import LisskinsOffer, LisskinsPurchase, LisskinsState
from csmarket.modules.orders import lisskins_buying
from csmarket.modules.orders.api import drain_paid
from csmarket.modules.orders.lisskins_buying import attempt_lisskins_buy
from csmarket.modules.orders.models import Order
from csmarket.modules.skinslink.models import SkinslinkItem, SkinslinkPurchase, SkinslinkState
from csmarket.modules.wallet.api import user_balance
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.integration.fake_lisskins_client import FakeLisskinsClient, purchase
from tests.integration.fake_trade_client import FakeTradeClient
from tests.integration.orders_factory import make_order

PRICE = Decimal(171_800)
COST = 12_340  # LIS-SKINS prices in cents; the ceiling is 12_340 × 1.03 → 12_710
OFFER = "7252638866"


@pytest.fixture
def settings() -> Settings:
    return get_settings().model_copy(
        update={
            "lisskins_enabled": True,
            "lisskins_api_key": "k",
            "waxpeer_api_key": "test-key-not-real",
        }
    )


async def _buying(
    db: AsyncSession, *, lots: tuple[tuple[int, int], ...] = ((5, COST),), status: str = "buying"
) -> Order:
    """A kassa-paid LIS-SKINS order (lot 5) and, while ``buying``, its pending purchase."""
    order = await make_order(
        db,
        status=status,
        paid_with="payme",
        paid_at=clock.now(),
        price_uzs=PRICE,
        source="lisskins",
        offer_id="ls:5",
        listing_id=None,
        cost_units=COST,
    )
    db.add_all(
        LisskinsOffer(id=lot, skin_item_id=order.skin_item_id, price_units=units, asset_id=str(lot))
        for lot, units in lots
    )
    await db.merge(LisskinsState(id=1, snapshot_at=clock.now(), lots=len(lots)))
    if status == "buying":
        db.add(
            LisskinsPurchase(
                order_id=order.id, custom_id=order.id, skin_id=5, paid_units=COST, buy_pending=True
            )
        )
    await db.commit()
    return order


async def _purchase(db: AsyncSession, order: Order) -> LisskinsPurchase:
    row = await db.scalar(
        select(LisskinsPurchase)
        .where(LisskinsPurchase.order_id == order.id)
        .execution_options(populate_existing=True)
    )
    assert row is not None
    return row


async def _order(db: AsyncSession, order: Order) -> Order:
    row = await db.scalar(
        select(Order).where(Order.id == order.id).execution_options(populate_existing=True)
    )
    assert row is not None
    return row


async def test_success_records_the_purchase_and_pays_at_most_the_cost(
    db_session: AsyncSession, settings: Settings
) -> None:
    order = await _buying(db_session)
    fake = FakeLisskinsClient(purchase("processing", custom_id=order.id))
    assert (
        await attempt_lisskins_buy(db_session, fake, order_id=order.id, settings=settings)
        == "bought"
    )
    assert fake.calls == [{"skin_id": 5, "custom_id": order.id, "max_price_usd": Decimal("12.34")}]
    p = await _purchase(db_session, order)
    assert (p.purchase_id, p.status, p.buy_pending, p.amount_units) == (
        55,
        "processing",
        False,
        12_340,
    )
    assert (await _order(db_session, order)).status == "buying"


async def test_a_wait_accept_answer_sends_the_trade(
    db_session: AsyncSession, settings: Settings
) -> None:
    order = await _buying(db_session)
    fake = FakeLisskinsClient(purchase("wait_accept", custom_id=order.id, offer_id=OFFER))
    assert (
        await attempt_lisskins_buy(db_session, fake, order_id=order.id, settings=settings)
        == "bought"
    )
    assert (await _order(db_session, order)).status == "trade_sent"
    assert (await _purchase(db_session, order)).steam_trade_offer_id == OFFER


async def test_a_lost_answer_is_unconfirmed_never_refunded(
    db_session: AsyncSession, settings: Settings
) -> None:
    order = await _buying(db_session)
    fake = FakeLisskinsClient(LisskinsUnavailableError("ReadTimeout"))
    assert await attempt_lisskins_buy(db_session, fake, order_id=order.id, settings=settings) == (
        "unconfirmed"
    )
    p = await _purchase(db_session, order)
    assert (p.buy_pending, p.buy_unconfirmed_at is not None) == (False, True)
    assert (await _order(db_session, order)).status == "buying"
    assert await user_balance(db_session, order.user_id) == Decimal(0)


async def test_a_repeat_after_a_lost_answer_adopts_the_stored_purchase(
    db_session: AsyncSession, settings: Settings
) -> None:
    order = await _buying(db_session)
    stored = purchase("wait_accept", custom_id=order.id, purchase_id=77, offer_id=OFFER)
    fake = FakeLisskinsClient(
        LisskinsUnavailableError("ReadTimeout"),
        LisskinsError("known", status=400, code="custom_id_already_exists"),
        infos={order.id: stored},
    )
    await attempt_lisskins_buy(db_session, fake, order_id=order.id, settings=settings)
    # The reconcile found nothing for a while and sends the same custom id again (Task 10).
    p = await _purchase(db_session, order)
    p.buy_pending, p.buy_unconfirmed_at = True, None
    (await _order(db_session, order)).next_check_at = None
    await db_session.commit()
    assert await attempt_lisskins_buy(db_session, fake, order_id=order.id, settings=settings) == (
        "adopted"
    )
    assert [c["custom_id"] for c in fake.calls] == [order.id, order.id]
    p = await _purchase(db_session, order)
    assert (p.purchase_id, p.buy_pending) == (77, False)
    assert (await _order(db_session, order)).status == "trade_sent"


async def test_a_known_custom_id_lis_skins_cannot_show_is_unconfirmed(
    db_session: AsyncSession, settings: Settings
) -> None:
    order = await _buying(db_session)
    fake = FakeLisskinsClient(LisskinsError("known", status=400, code="custom_id_already_exists"))
    assert await attempt_lisskins_buy(db_session, fake, order_id=order.id, settings=settings) == (
        "unconfirmed"
    )


async def test_a_sold_lot_substitutes_once_then_refunds(
    db_session: AsyncSession, settings: Settings
) -> None:
    order = await _buying(db_session, lots=((5, COST), (6, COST + 100)))
    fake = FakeLisskinsClient(
        LisskinsError("gone", status=400, code="skins_unavailable", unavailable_ids=(5,)),
        LisskinsError("dearer", status=400, code="skins_price_higher_than_max_price"),
    )
    assert (
        await attempt_lisskins_buy(db_session, fake, order_id=order.id, settings=settings)
        == "sold_out"
    )
    assert [c["skin_id"] for c in fake.calls] == [5, 6]
    assert fake.calls[1]["custom_id"] == f"{order.id}:2"
    assert fake.calls[1]["max_price_usd"] == Decimal("12.44")
    row = await _order(db_session, order)
    assert (row.status, row.failure_reason) == ("failed", "sold_out")
    assert await user_balance(db_session, order.user_id) == PRICE


async def test_a_lisskins_substitute_is_bought_under_a_second_id(
    db_session: AsyncSession, settings: Settings
) -> None:
    order = await _buying(db_session, lots=((5, COST), (6, COST + 100)))
    fake = FakeLisskinsClient(
        LisskinsError("gone", status=400, code="skins_unavailable"),
        purchase("processing", custom_id=f"{order.id}:2", purchase_id=56, id=6),
    )
    assert (
        await attempt_lisskins_buy(db_session, fake, order_id=order.id, settings=settings)
        == "bought"
    )
    p = await _purchase(db_session, order)
    assert (p.custom_id, p.skin_id, p.paid_units, p.purchase_id) == (
        f"{order.id}:2",
        6,
        COST + 100,
        56,
    )


async def test_a_substitute_above_the_ceiling_is_never_bought(
    db_session: AsyncSession, settings: Settings
) -> None:
    order = await _buying(db_session, lots=((5, COST), (6, 12_711)))
    fake = FakeLisskinsClient(LisskinsError("gone", status=400, code="skins_unavailable"))
    assert (
        await attempt_lisskins_buy(db_session, fake, order_id=order.id, settings=settings)
        == "sold_out"
    )
    assert len(fake.calls) == 1


async def test_a_skinslink_substitute_hands_the_order_to_the_skinslink_path(
    db_session: AsyncSession, settings: Settings
) -> None:
    order = await _buying(db_session)
    db_session.add(
        SkinslinkItem(
            id="100",
            market_hash_name=order.market_hash_name,
            phase="",
            price_units=COST,
            skin_item_id=order.skin_item_id,
        )
    )
    await db_session.merge(SkinslinkState(id=1, cursor="c", mirror_synced_at=clock.now()))
    await db_session.commit()
    on = settings.model_copy(
        update={"skinslink_enabled": True, "skinslink_api_key": "k", "skinslink_secret": "s"}
    )
    fake = FakeLisskinsClient(LisskinsError("gone", status=400, code="skins_unavailable"))
    assert (
        await attempt_lisskins_buy(db_session, fake, order_id=order.id, settings=on)
        == "lookup_later"
    )
    row = await _order(db_session, order)
    assert (row.source, row.offer_id, row.status) == ("skinslink", "sl:100", "buying")
    sl = await db_session.scalar(
        select(SkinslinkPurchase).where(SkinslinkPurchase.order_id == order.id)
    )
    assert sl is not None
    assert sl.merchant_tx_id == f"{order.id}:2"


@pytest.mark.parametrize(
    ("code", "reason"),
    [
        ("insufficient_funds", "source_low_balance"),
        ("invalid_trade_url", "invalid_trade_link"),
        ("user_trade_ban", "invalid_trade_link"),
        ("user_cant_trade", "invalid_trade_link"),
        ("private_inventory", "invalid_trade_link"),
        ("too_many_failed_attempts_for_user", "invalid_trade_link"),
        ("invalid_partner_value", "invalid_trade_link"),
    ],
)
async def test_refund_reasons(
    db_session: AsyncSession, settings: Settings, code: str, reason: str
) -> None:
    order = await _buying(db_session, lots=((5, COST), (6, COST)))
    status = 422 if code.startswith("invalid_partner") else 400
    fake = FakeLisskinsClient(LisskinsError("no", status=status, code=code))
    await attempt_lisskins_buy(db_session, fake, order_id=order.id, settings=settings)
    row = await _order(db_session, order)
    assert (row.status, row.failure_reason) == ("failed", reason)
    assert len(fake.calls) == 1  # never a substitute: every lot would be refused the same way
    assert await user_balance(db_session, order.user_id) == PRICE


async def test_forbidden_is_an_attention_and_keeps_the_buy_pending(
    db_session: AsyncSession, settings: Settings
) -> None:
    order = await _buying(db_session)
    fake = FakeLisskinsClient(LisskinsForbiddenError("forbidden", status=401))
    assert (
        await attempt_lisskins_buy(db_session, fake, order_id=order.id, settings=settings)
        == "forbidden"
    )
    p = await _purchase(db_session, order)
    assert (p.attention_reason, p.buy_pending) == ("source_forbidden", True)


async def test_429_waits_for_its_retry_after(db_session: AsyncSession, settings: Settings) -> None:
    order = await _buying(db_session)
    fake = FakeLisskinsClient(LisskinsRateLimitedError("slow", retry_after=45))
    assert await attempt_lisskins_buy(db_session, fake, order_id=order.id, settings=settings) == (
        "rate_limited"
    )
    assert (await _purchase(db_session, order)).buy_pending is True
    row = await _order(db_session, order)
    assert row.next_check_at is not None
    assert row.next_check_at >= clock.now() + timedelta(seconds=44)


async def test_a_rerun_after_the_substitute_never_substitutes_again(
    db_session: AsyncSession, settings: Settings
) -> None:
    order = await _buying(db_session, lots=((5, COST), (6, 12_400), (7, 12_500)))
    p = await _purchase(db_session, order)
    p.custom_id, p.skin_id, p.paid_units = f"{order.id}:2", 6, 12_400
    await db_session.commit()
    fake = FakeLisskinsClient(LisskinsError("gone", status=400, code="skins_unavailable"))
    assert (
        await attempt_lisskins_buy(db_session, fake, order_id=order.id, settings=settings)
        == "sold_out"
    )
    assert [c["custom_id"] for c in fake.calls] == [f"{order.id}:2"]


async def test_a_settled_buy_is_never_bought_again(
    db_session: AsyncSession, settings: Settings
) -> None:
    order = await _buying(db_session)
    fake = FakeLisskinsClient(purchase("processing", custom_id=order.id))
    await attempt_lisskins_buy(db_session, fake, order_id=order.id, settings=settings)
    assert await attempt_lisskins_buy(db_session, fake, order_id=order.id, settings=settings) == (
        "nothing_to_do"
    )
    assert len(fake.calls) == 1


async def test_an_unreadable_trade_link_refunds_without_a_call(
    db_session: AsyncSession, settings: Settings
) -> None:
    order = await _buying(db_session)
    row = await _order(db_session, order)
    row.trade_link = "not a trade link"
    await db_session.commit()
    fake = FakeLisskinsClient()
    assert await attempt_lisskins_buy(db_session, fake, order_id=order.id, settings=settings) == (
        "invalid_link"
    )
    assert fake.calls == []


async def test_drain_paid_buys_a_lisskins_order(
    db_session: AsyncSession, settings: Settings
) -> None:
    order = await _buying(db_session, status="paid")
    fake = FakeLisskinsClient(purchase("processing", custom_id=order.id))
    claimed = await drain_paid(
        db_session, client=FakeTradeClient(), lisskins_client=fake, settings=settings
    )
    assert claimed == 1
    assert fake.calls[0]["custom_id"] == order.id
    p = await _purchase(db_session, order)
    assert (p.skin_id, p.paid_units, p.buy_pending) == (5, COST, False)


# --- the attempt's exits: a timeout, a crash, rows moved during the call -----------------


class _Slow(FakeLisskinsClient):
    """Answers after the attempt's budget ran out."""

    async def buy(self, **kw: object) -> Purchase:  # type: ignore[override]
        self.calls.append(dict(kw))
        await asyncio.sleep(5)
        raise AssertionError("never reached")


class _Crash(FakeLisskinsClient):
    """A bug after the buy request went out."""

    async def buy(self, **kw: object) -> Purchase:  # type: ignore[override]
        self.calls.append(dict(kw))
        raise RuntimeError("a bug after the buy was sent")


class _Moves(FakeLisskinsClient):
    """The order leaves ``buying`` while LIS-SKINS answers (a sweep, an admin)."""

    def __init__(self, engine: AsyncEngine, answer: object) -> None:
        super().__init__(answer)
        self.engine = engine

    async def buy(self, **kw: object) -> Purchase:  # type: ignore[override]
        async with AsyncSession(bind=self.engine) as other:
            await other.execute(
                update(Order).values(status="failed").where(Order.id == kw["custom_id"])
            )
            await other.commit()
        return await super().buy(**kw)  # type: ignore[arg-type]


async def test_a_buy_that_outlives_its_budget_is_unconfirmed_never_rebought(
    db_session: AsyncSession, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(lisskins_buying, "ATTEMPT_BUDGET", timedelta(milliseconds=300))
    order = await _buying(db_session)
    fake = _Slow()
    outcome = await attempt_lisskins_buy(db_session, fake, order_id=order.id, settings=settings)
    assert outcome == "unconfirmed"
    p = await _purchase(db_session, order)
    assert (p.buy_pending, p.buy_unconfirmed_at is not None) == (False, True)
    again = await attempt_lisskins_buy(db_session, fake, order_id=order.id, settings=settings)
    assert again == "nothing_to_do"
    assert len(fake.calls) == 1


async def test_an_unrecordable_timeout_keeps_the_lease(
    db_session: AsyncSession, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(lisskins_buying, "ATTEMPT_BUDGET", timedelta(milliseconds=300))

    async def broken(*_: object, **__: object) -> bool:
        raise RuntimeError("the database is gone")

    monkeypatch.setattr(lisskins_buying, "secure_sent", broken)
    order = await _buying(db_session)
    outcome = await attempt_lisskins_buy(db_session, _Slow(), order_id=order.id, settings=settings)
    assert outcome == "unrecorded"
    assert (await _purchase(db_session, order)).buy_pending is True
    row = await _order(db_session, order)
    assert row.next_check_at is not None
    assert row.next_check_at > clock.now()  # the lease lapses, nobody buys again within it


async def test_a_crash_after_the_request_marks_the_buy_unconfirmed(
    db_session: AsyncSession, settings: Settings
) -> None:
    order = await _buying(db_session)
    with pytest.raises(RuntimeError):
        await attempt_lisskins_buy(db_session, _Crash(), order_id=order.id, settings=settings)
    p = await _purchase(db_session, order)
    assert (p.buy_pending, p.buy_unconfirmed_at is not None) == (False, True)


async def test_a_purchase_landing_on_moved_rows_is_flagged(
    db_session: AsyncSession, db_engine: AsyncEngine, settings: Settings
) -> None:
    order = await _buying(db_session)
    fake = _Moves(db_engine, purchase("processing", custom_id=order.id))
    outcome = await attempt_lisskins_buy(db_session, fake, order_id=order.id, settings=settings)
    assert outcome == "stale_bought"
    assert (await _purchase(db_session, order)).attention_reason == "ambiguous_trade"


async def test_a_refusal_on_moved_rows_writes_nothing(
    db_session: AsyncSession, db_engine: AsyncEngine, settings: Settings
) -> None:
    order = await _buying(db_session)
    refused = LisskinsError("broke", status=400, code="insufficient_funds")
    fake = _Moves(db_engine, refused)
    outcome = await attempt_lisskins_buy(db_session, fake, order_id=order.id, settings=settings)
    assert outcome == "nothing_to_do"
    assert (await _order(db_session, order)).refunded_at is None
