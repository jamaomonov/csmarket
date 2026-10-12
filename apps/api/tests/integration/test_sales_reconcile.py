"""The poll: open sales every minute, ``hold`` every 30 min; one credit when checks race."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from decimal import Decimal

import pytest
from csmarket.core.clock import now
from csmarket.modules.sales.reconcile import (
    attention_open,
    holds_overdue,
    payouts_overdue,
    poll_sales,
)
from csmarket.modules.sales.status import check_sale
from csmarket.modules.wallet.api import WalletTransaction, user_balance
from prometheus_client import REGISTRY
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.integration.fake_deposit_client import FakeDepositClient, deposit
from tests.integration.sales_factory import make_request, make_sale

pytestmark = pytest.mark.asyncio


async def test_open_sales_every_minute_and_hold_every_half_hour(
    db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    at = now()
    await make_sale(db_session, status="offered", last_polled_at=at - timedelta(seconds=30))
    offered = await make_sale(
        db_session, status="offered", last_polled_at=at - timedelta(seconds=61)
    )
    creating = await make_sale(db_session, status="creating")
    await make_sale(db_session, status="hold", last_polled_at=at - timedelta(minutes=10))
    hold = await make_sale(db_session, status="hold", last_polled_at=at - timedelta(minutes=31))
    await make_sale(db_session, status="credited")
    client = FakeDepositClient(status=deposit("active"))
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    assert await poll_sales(factory, client, at=at) == 3
    assert set(client.status_calls) == {offered.id, creating.id, hold.id}


async def test_two_checks_racing_on_completed_credit_once(
    db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    sale = await make_sale(db_session, status="hold", payout_uzs=Decimal(158_300))
    client = FakeDepositClient(status=deposit("completed"))
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)

    async def one() -> str:
        async with factory() as db:
            return await check_sale(db, client, sale_id=sale.id)

    assert sorted(await asyncio.gather(one(), one())) == ["credited", "unchanged"]
    assert await user_balance(db_session, sale.user_id) == Decimal(158_300)
    count = await db_session.scalar(
        select(func.count())
        .select_from(WalletTransaction)
        .where(WalletTransaction.reference_id == sale.id)
    )
    assert count == 1


async def test_overdue_payouts_are_counted_and_exported(
    db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    at = now()
    old = await make_sale(db_session, status="payout", payout_to="card")
    # Sellers are promised the card within 12 h of the hold; the alarm rings at 10 h.
    await make_request(db_session, old, status="to_pay", to_pay_at=at - timedelta(hours=11))
    young = await make_sale(db_session, status="payout", payout_to="card")
    await make_request(db_session, young, status="to_pay", to_pay_at=at - timedelta(hours=9))
    assert await payouts_overdue(db_session, at=at) == 1
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    await poll_sales(factory, FakeDepositClient(status=None), at=at)
    assert REGISTRY.get_sample_value("csmarket_sale_payouts_overdue") == 1.0


async def test_one_failing_sale_never_stops_the_tick(
    db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    await make_sale(db_session, status="offered")
    await make_sale(db_session, status="offered")
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    client = FakeDepositClient(status=RuntimeError("boom"))
    assert await poll_sales(factory, client) == 2
    assert len(client.status_calls) == 2


async def test_a_sale_closed_not_created_is_asked_about_for_a_day(
    db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    """SB-1: a slow ``create-deposit`` may have sent the offer after all."""
    at = now()
    recent = await make_sale(db_session, status="closed", fail_reason="not_created")
    await make_sale(
        db_session,
        status="closed",
        fail_reason="not_created",
        last_polled_at=at - timedelta(minutes=2),
    )
    await make_sale(
        db_session,
        status="closed",
        fail_reason="not_created",
        created_at=at - timedelta(hours=25),
    )
    await make_sale(db_session, status="closed", fail_reason="canceled")
    client = FakeDepositClient(status=deposit("hold"))
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    assert await poll_sales(factory, client, at=at) == 1
    assert client.status_calls == [recent.id]
    await db_session.refresh(recent)
    assert recent.status == "hold"


async def test_the_tick_exports_open_attentions_and_overdue_holds(
    db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    at = now()
    await make_sale(db_session, status="credited", attention_reason="rolled_back")
    await make_sale(db_session, status="credited", attention_reason="rolled_back", resolved_at=at)
    await make_sale(db_session, status="closed", attention_reason="late_deposit")
    stuck = at - timedelta(hours=7)
    await make_sale(db_session, status="hold", hold_end_at=stuck, last_polled_at=at)
    await make_sale(
        db_session, status="hold", hold_end_at=at - timedelta(hours=1), last_polled_at=at
    )
    assert await attention_open(db_session) == {
        "rolled_back": 1,
        "late_deposit": 1,
        "credit_blocked": 0,
    }
    assert await holds_overdue(db_session, at=at) == 1
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    await poll_sales(factory, FakeDepositClient(status=None), at=at)
    sample = REGISTRY.get_sample_value
    assert sample("csmarket_sale_attention_open", {"reason": "rolled_back"}) == 1.0
    assert sample("csmarket_sale_attention_open", {"reason": "credit_blocked"}) == 0.0
    assert sample("csmarket_sale_holds_overdue") == 1.0
