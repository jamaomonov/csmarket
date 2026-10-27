"""Rewards: written for delivered orders of attributed buyers, credited after the 8-day hold
(spec 2026-10-27-referrals «Calls I made», Review Focus 1, 4, 5)."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from csmarket.core.clock import now
from csmarket.modules.admin.users_service import unban
from csmarket.modules.orders.trades import flag
from csmarket.modules.public_api.models import ApiKey
from csmarket.modules.referrals.models import ReferralPartner, ReferralReward
from csmarket.modules.referrals.partners import update_partner
from csmarket.modules.referrals.rewards import accrue, settle, stuck_count
from csmarket.modules.referrals.schemas import PartnerPatch
from csmarket.modules.users.models import User
from csmarket.modules.wallet.api import user_account, user_balance
from csmarket.modules.wallet.models import WalletTransaction
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.orders_factory import make_trade
from tests.integration.payments_factory import make_user
from tests.integration.referrals_factory import attribute, make_partner, make_reward
from tests.integration.reviews_factory import delivered_order
from tests.integration.skinslink_factory import make_skinslink_order

pytestmark = pytest.mark.asyncio


async def _rewards(db: AsyncSession) -> list[ReferralReward]:
    db.expire_all()
    return list((await db.scalars(select(ReferralReward))).all())


async def _setup(
    db: AsyncSession,
    *,
    days_ago: float = 40,
    **partner: Any,  # Any: column values of any type, as make_partner takes them
) -> tuple[ReferralPartner, User]:
    p = await make_partner(db, **partner)
    buyer = await make_user(db)
    await attribute(db, user=buyer, partner=p, at=now() - timedelta(days=days_ago))
    return p, buyer


async def test_accrues_a_delivered_order_in_term(db_session: AsyncSession) -> None:
    partner, buyer = await _setup(db_session, percent=Decimal("1.5"))
    order_id = (await delivered_order(db_session, user=buyer, price_uzs=Decimal(171_800))).id
    partner_id = partner.user_id
    assert await accrue(db_session) == 1
    [r] = await _rewards(db_session)
    assert r.order_id == order_id
    assert r.partner_id == partner_id
    assert r.amount_uzs == Decimal(2577)  # floor(171 800 × 1.5 %)
    assert r.status == "held"
    assert r.available_at == r.delivered_at + timedelta(days=8)


async def test_skips_api_orders_undelivered_and_before_attribution(
    db_session: AsyncSession,
) -> None:
    _, buyer = await _setup(db_session, days_ago=5)
    await delivered_order(db_session, user=buyer, days_ago=6)  # before the attribution
    await delivered_order(db_session, user=buyer, status="trade_sent")
    key = ApiKey(user_id=buyer.id, token_hash=uuid4().hex * 2, pricing_profile="cost")
    db_session.add(key)
    await db_session.commit()
    await delivered_order(
        db_session,
        user=buyer,
        channel="api",
        api_key_id=key.id,
        client_order_id="c-1",
        pricing_profile="cost",
    )
    await delivered_order(db_session)  # a buyer nobody brought
    assert await accrue(db_session) == 0


async def test_term_end_is_exclusive_and_forever_has_none(db_session: AsyncSession) -> None:
    attributed = now() - timedelta(days=40)
    p = await make_partner(db_session, term_months=1)
    buyer = await make_user(db_session)
    await attribute(db_session, user=buyer, partner=p, at=attributed)
    # the term ends one calendar month later, by Postgres month arithmetic
    edge = await db_session.scalar(
        text("SELECT CAST(:at AS timestamptz) + make_interval(months => 1)"), {"at": attributed}
    )
    inside = (
        await delivered_order(db_session, user=buyer, delivered_at=edge - timedelta(minutes=1))
    ).id
    await delivered_order(db_session, user=buyer, delivered_at=edge)
    forever = await make_partner(db_session, term_months=None)
    old_buyer = await make_user(db_session)
    await attribute(db_session, user=old_buyer, partner=forever, at=now() - timedelta(days=5 * 365))
    late = (await delivered_order(db_session, user=old_buyer)).id
    assert await accrue(db_session) == 2
    assert {r.order_id for r in await _rewards(db_session)} == {inside, late}


async def test_inactive_or_banned_partner_earns_nothing_new(db_session: AsyncSession) -> None:
    _, buyer = await _setup(db_session, active=False)
    await delivered_order(db_session, user=buyer)
    partner, other = await _setup(db_session)
    owner = await db_session.get(User, partner.user_id)
    assert owner is not None
    owner.banned_at = now()
    await db_session.commit()
    await delivered_order(db_session, user=other)
    assert await accrue(db_session) == 0


async def test_accrue_is_idempotent(db_session: AsyncSession) -> None:
    _, buyer = await _setup(db_session)
    await delivered_order(db_session, user=buyer)
    assert await accrue(db_session) == 1
    assert await accrue(db_session) == 0
    assert len(await _rewards(db_session)) == 1


async def test_floor_and_zero_not_booked(db_session: AsyncSession) -> None:
    _, buyer = await _setup(db_session, percent=Decimal("0.1"))
    await delivered_order(db_session, user=buyer, price_uzs=Decimal(999))  # floor → 0
    kept = (await delivered_order(db_session, user=buyer, price_uzs=Decimal(1000))).id
    assert await accrue(db_session) == 1
    [r] = await _rewards(db_session)
    assert (r.order_id, r.amount_uzs) == (kept, Decimal(1))


async def _due(
    db: AsyncSession,
    **over: Any,  # Any: column values of any type, as make_reward takes them
) -> tuple[ReferralPartner, ReferralReward]:
    partner, buyer = await _setup(db)
    order = await delivered_order(db, user=buyer, days_ago=9)
    reward = await make_reward(db, partner=partner, order=order, **over)
    return partner, reward


async def test_settle_credits_after_the_hold_only(db_session: AsyncSession) -> None:
    partner, due = await _due(db_session)
    _, buyer = await _setup(db_session)
    fresh = await delivered_order(db_session, user=buyer, days_ago=2)
    await make_reward(db_session, partner=partner, order=fresh)
    due_id, fresh_id, partner_id, amount = due.order_id, fresh.id, partner.user_id, due.amount_uzs
    result = await settle(db_session)
    assert (result.credited, result.cancelled, result.waiting) == (1, 0, 0)
    rows = {r.order_id: r for r in await _rewards(db_session)}
    assert rows[due_id].status == "credited"
    assert rows[due_id].credited_at is not None
    assert rows[fresh_id].status == "held"
    assert await user_balance(db_session, partner_id) == amount


async def test_rolled_back_is_cancelled_even_if_resolved(db_session: AsyncSession) -> None:
    partner, buyer = await _setup(db_session)
    wax = await delivered_order(db_session, user=buyer, days_ago=9)
    await make_trade(
        db_session, wax, attention_reason="rolled_back", resolved_at=now() - timedelta(days=1)
    )
    await make_reward(db_session, partner=partner, order=wax)
    sl, _ = await make_skinslink_order(
        db_session,
        status="delivered",
        order={"user_id": buyer.id, "delivered_at": now() - timedelta(days=9)},
        attention_reason="rolled_back",
    )
    await make_reward(db_session, partner=partner, order=sl)
    partner_id = partner.user_id
    result = await settle(db_session)
    assert (result.credited, result.cancelled) == (0, 2)
    for r in await _rewards(db_session):
        assert (r.status, r.cancelled_reason) == ("cancelled", "rolled_back")
    assert await user_balance(db_session, partner_id) == 0


async def test_open_attention_waits_then_credits_after_resolution(
    db_session: AsyncSession,
) -> None:
    partner, buyer = await _setup(db_session)
    order = await delivered_order(db_session, user=buyer, days_ago=9)
    trade = await make_trade(db_session, order, attention_reason="audit_divergence")
    await make_reward(db_session, partner=partner, order=order)
    assert (await settle(db_session)).waiting == 1
    trade.resolved_at = now()
    await db_session.commit()
    assert (await settle(db_session)).credited == 1


async def test_frozen_wallet_waits_and_others_credit(db_session: AsyncSession) -> None:
    frozen_partner, frozen = await _due(db_session)
    wallet = await user_account(db_session, frozen_partner.user_id)
    wallet.status = "frozen"
    await db_session.commit()
    banned_partner, banned = await _due(db_session)
    owner = await db_session.get(User, banned_partner.user_id)
    assert owner is not None
    owner.banned_at = now()
    await db_session.commit()
    fine_partner, fine = await _due(db_session)
    ids = (frozen.order_id, banned.order_id, fine.order_id)
    fine_id, fine_amount = fine_partner.user_id, fine.amount_uzs
    result = await settle(db_session)
    assert (result.credited, result.waiting) == (1, 2)
    status = {r.order_id: r.status for r in await _rewards(db_session)}
    assert status == dict(zip(ids, ("held", "held", "credited"), strict=True))
    assert await user_balance(db_session, fine_id) == fine_amount


async def test_settle_twice_books_once(db_session: AsyncSession) -> None:
    await _due(db_session)
    first = await settle(db_session)
    second = await settle(db_session)
    assert (first.credited, second.credited) == (1, 0)
    count = await db_session.scalar(
        select(func.count())
        .select_from(WalletTransaction)
        .where(WalletTransaction.kind == "referral_reward")
    )
    assert count == 1


async def test_switched_off_then_on_earns_nothing_for_the_off_days(
    db_session: AsyncSession,
) -> None:
    partner, buyer = await _setup(db_session)
    partner_id = partner.user_id
    admin_id = (await make_user(db_session)).id
    await update_partner(
        db_session, user_id=partner_id, patch=PartnerPatch(active=False), admin_id=admin_id
    )
    await db_session.commit()
    off = (await delivered_order(db_session, user=buyer, days_ago=0)).id
    await update_partner(
        db_session, user_id=partner_id, patch=PartnerPatch(active=True), admin_id=admin_id
    )
    await db_session.commit()
    on = (await delivered_order(db_session, user=buyer, days_ago=0)).id
    assert await accrue(db_session) == 1
    assert {r.order_id for r in await _rewards(db_session)} == {on}
    assert off != on


async def test_waiting_rewards_do_not_block_the_rest(db_session: AsyncSession) -> None:
    stuck, buyer = await _setup(db_session)
    owner = await db_session.get(User, stuck.user_id)
    assert owner is not None
    owner.banned_at = now()
    await db_session.commit()
    for days in (12, 11):  # the oldest due rows, and they can only wait
        order = await delivered_order(db_session, user=buyer, days_ago=days)
        await make_reward(db_session, partner=stuck, order=order)
    _, fine = await _due(db_session)  # due later than the stuck ones
    fine_id = fine.order_id
    first = await settle(db_session, limit=2)
    second = await settle(db_session, limit=2)
    assert (first.credited, first.waiting) == (0, 2)
    assert second.credited == 1
    status = {r.order_id: r.status for r in await _rewards(db_session)}
    assert status[fine_id] == "credited"


async def test_a_rollback_overwritten_by_another_attention_still_cancels(
    db_session: AsyncSession,
) -> None:
    partner, buyer = await _setup(db_session)
    order = await delivered_order(db_session, user=buyer, days_ago=9)
    trade = await make_trade(db_session, order)
    await make_reward(db_session, partner=partner, order=order)
    flag(trade, "rolled_back")
    trade.resolved_at = now()  # the admin resolved it
    flag(trade, "audit_divergence", reopen=True)  # the audit opens another one on top
    trade.resolved_at = now()  # …and that is resolved too
    await db_session.commit()
    result = await settle(db_session)
    assert (result.credited, result.cancelled) == (0, 1)


async def test_stuck_counts_held_rewards_days_past_their_hold(db_session: AsyncSession) -> None:
    partner, buyer = await _setup(db_session)
    for days in (20, 9):  # due 12 days ago (stuck) and 1 day ago (not yet)
        order = await delivered_order(db_session, user=buyer, days_ago=days)
        await make_reward(db_session, partner=partner, order=order)
    done = await delivered_order(db_session, user=buyer, days_ago=30)
    await make_reward(db_session, partner=partner, order=done, status="credited")
    assert await stuck_count(db_session) == 1


async def test_unbanned_partner_earns_nothing_for_the_ban_days(db_session: AsyncSession) -> None:
    partner, buyer = await _setup(db_session)
    admin = await make_user(db_session)
    owner = await db_session.get(User, partner.user_id)
    assert owner is not None
    owner.banned_at = now()
    await db_session.commit()
    banned_day = (await delivered_order(db_session, user=buyer, days_ago=0)).id
    owner = await db_session.get(User, partner.user_id)
    assert owner is not None
    await unban(db_session, admin=admin, user=owner, reason="разобрались")
    await db_session.commit()
    after = (await delivered_order(db_session, user=buyer, days_ago=0)).id
    assert await accrue(db_session) == 1
    assert {r.order_id for r in await _rewards(db_session)} == {after}
    assert banned_day != after
