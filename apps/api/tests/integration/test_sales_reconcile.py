"""The poll: open sales every minute, ``hold`` every 30 min; one credit when checks race."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from decimal import Decimal

import pytest
from csmarket.core.clock import now
from csmarket.modules.sales.reconcile import payouts_overdue, poll_sales
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
    await make_request(db_session, old, status="to_pay", to_pay_at=at - timedelta(hours=49))
    young = await make_sale(db_session, status="payout", payout_to="card")
    await make_request(db_session, young, status="to_pay", to_pay_at=at - timedelta(hours=1))
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
