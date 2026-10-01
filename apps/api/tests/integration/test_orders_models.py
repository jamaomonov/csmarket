"""``orders`` and ``skin_trades`` against a real Postgres: defaults, the per-user idempotency
key, the check constraints, and the ``payments`` purpose check that now covers orders."""

from __future__ import annotations

from decimal import Decimal

import pytest
from csmarket.core.ids import new_id
from csmarket.modules.fx.models import FxSnapshot
from csmarket.modules.orders.models import Order, SkinTrade
from csmarket.modules.payments.models import Payment
from csmarket.modules.skins.models import SkinItem
from csmarket.modules.users.models import User
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.orders_factory import build_order, make_item_and_rate
from tests.integration.payments_factory import make_topup, make_user


async def _parents(db: AsyncSession) -> tuple[User, SkinItem, FxSnapshot]:
    user = await make_user(db)
    item, fx = await make_item_and_rate(db)
    return user, item, fx


async def _order(
    db: AsyncSession,
    parents: tuple[User, SkinItem, FxSnapshot],
    **overrides: object,
) -> Order:
    user, item, fx = parents
    return await build_order(db, user=user, item=item, fx=fx, **overrides)


async def test_order_and_trade_round_trip_with_defaults(db_session: AsyncSession) -> None:
    order = await _order(db_session, await _parents(db_session))
    await db_session.flush()
    db_session.add(
        SkinTrade(
            order_id=order.id, project_id=order.id, listing_id=order.listing_id, paid_units=12_345
        )
    )
    await db_session.commit()
    fetched = (
        await db_session.execute(
            select(Order).where(Order.id == order.id).execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert (fetched.status, fetched.phase, fetched.paid_with) == ("pending", "", None)
    assert fetched.cost_usd == Decimal("12.345000")
    assert fetched.price_uzs == Decimal(171_800)
    assert fetched.created_at is not None
    assert fetched.updated_at is not None
    assert fetched.paid_at is None
    assert fetched.refunded_to is None
    trade = (
        await db_session.execute(
            select(SkinTrade)
            .where(SkinTrade.order_id == order.id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert trade.project_id == order.id
    assert trade.status is None
    assert trade.waxpeer_id is None
    assert (trade.is_released, trade.buy_pending) == (False, False)
    assert trade.seller == {}
    assert trade.penalties is None
    assert trade.attention_reason is None
    assert trade.created_at is not None
    assert trade.updated_at is not None


async def test_an_idempotency_key_is_unique_per_user(db_session: AsyncSession) -> None:
    parents = await _parents(db_session)
    await _order(db_session, parents, idempotency_key="same-key-0123456789")
    await db_session.flush()
    await _order(db_session, parents, idempotency_key="same-key-0123456789")
    with pytest.raises(IntegrityError, match="uq_orders_user_id_idempotency_key"):
        async with db_session.begin_nested():
            await db_session.flush()


async def test_another_user_may_reuse_the_key(db_session: AsyncSession) -> None:
    user, item, fx = await _parents(db_session)
    other = await make_user(db_session)
    await _order(db_session, (user, item, fx), idempotency_key="same-key-0123456789")
    await _order(db_session, (other, item, fx), idempotency_key="same-key-0123456789")
    await db_session.commit()


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"status": "shipped"}, "ck_orders_status"),
        ({"refunded_to": "card"}, "ck_orders_refunded_to"),
    ],
)
async def test_order_checks_refuse_other_values(
    db_session: AsyncSession, overrides: dict[str, object], constraint: str
) -> None:
    await _order(db_session, await _parents(db_session), **overrides)
    with pytest.raises(IntegrityError, match=constraint):
        async with db_session.begin_nested():
            await db_session.flush()


async def test_attention_reason_check_refuses_other_values(db_session: AsyncSession) -> None:
    order = await _order(db_session, await _parents(db_session))
    await db_session.flush()
    db_session.add(
        SkinTrade(
            order_id=order.id,
            project_id=order.id,
            listing_id=1,
            paid_units=1,
            attention_reason="whatever",
        )
    )
    with pytest.raises(IntegrityError, match="ck_skin_trades_attention_reason"):
        async with db_session.begin_nested():
            await db_session.flush()


async def test_deleting_an_order_cascades_to_its_trade(db_session: AsyncSession) -> None:
    order = await _order(db_session, await _parents(db_session))
    await db_session.flush()
    db_session.add(SkinTrade(order_id=order.id, project_id=order.id, listing_id=1, paid_units=1))
    await db_session.commit()
    await db_session.delete(order)
    await db_session.commit()
    assert (await db_session.execute(select(SkinTrade))).first() is None


def _payment(user_id: str, **kw: str | None) -> Payment:
    return Payment(
        id=new_id(),
        number="ABCDEFGH",
        user_id=user_id,
        provider="wallet",
        amount_uzs=Decimal(171_800),
        status="succeeded",
        **kw,
    )


async def test_an_order_payment_needs_its_order(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    db_session.add(_payment(user.id, purpose="order", order_id=None))
    with pytest.raises(IntegrityError, match="ck_payments_purpose_order"):
        async with db_session.begin_nested():
            await db_session.flush()


async def test_a_topup_payment_cannot_carry_an_order(db_session: AsyncSession) -> None:
    parents = await _parents(db_session)
    order = await _order(db_session, parents)
    topup = await make_topup(db_session, user=parents[0])
    db_session.add(_payment(parents[0].id, purpose="topup", topup_id=topup.id, order_id=order.id))
    with pytest.raises(IntegrityError, match="ck_payments_purpose_order"):
        async with db_session.begin_nested():
            await db_session.flush()


async def test_an_order_payment_points_at_a_real_order(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    db_session.add(_payment(user.id, purpose="order", order_id=new_id()))
    with pytest.raises(IntegrityError, match="fk_payments_order_id_orders"):
        async with db_session.begin_nested():
            await db_session.flush()


async def test_an_order_payment_round_trips(db_session: AsyncSession) -> None:
    parents = await _parents(db_session)
    order = await _order(db_session, parents, status="paid", paid_with="wallet")
    await db_session.flush()
    db_session.add(_payment(parents[0].id, purpose="order", order_id=order.id))
    await db_session.commit()
    paid = (
        await db_session.execute(select(Payment).where(Payment.order_id == order.id))
    ).scalar_one()
    assert paid.provider == "wallet"
