"""The kassa timeout sweeps cover order attempts (M4a): Click ``cancel_stale``, Payme
``cancel_stale``, Uzum ``fail_stale``.

Each sweep releases a stale order attempt and never touches the order's status (the order
expiry sweep owns that); per row it locks the owner (top-up or order) ``FOR UPDATE SKIP
LOCKED`` first, so an order a callback holds is left for the next tick. No sleeping: the
kassa rows' creation times are moved back directly.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

import pytest
from csmarket.core import clock
from csmarket.modules.click import service as click_svc
from csmarket.modules.click.models import ClickTransaction
from csmarket.modules.orders.models import Order
from csmarket.modules.payme import service as payme_svc
from csmarket.modules.payme.models import PaymeTransaction
from csmarket.modules.payments.models import Payment, WalletTopup
from csmarket.modules.payments.payable import resolve
from csmarket.modules.uzum import service as uzum_svc
from csmarket.modules.uzum.models import UzumTransaction
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.integration.orders_factory import make_order
from tests.integration.payments_factory import make_topup

PRICE = Decimal(171_800)
_DAY_MS = 24 * 3600 * 1000


@dataclass(frozen=True)
class Kassa:
    """One kassa's way to open a stale transaction, sweep, and read the row back."""

    name: str
    open_stale: Callable[[AsyncSession, str, Decimal, str], Awaitable[None]]
    sweep: Callable[[AsyncSession], Awaitable[int]]
    read: Callable[[AsyncSession, str], Awaitable[tuple[str, str]]]


async def _payment_status(db: AsyncSession, payment_id: str) -> str:
    stmt = select(Payment.status).where(Payment.id == payment_id)
    return str((await db.execute(stmt)).scalar_one())


async def _click_open(db: AsyncSession, number: str, amount: Decimal, key: str) -> None:
    await click_svc.prepare(
        db,
        click_trans_id=int(key),
        service_id=108149,
        click_paydoc_id=int(key),
        merchant_trans_id=number,
        amount=str(amount),
    )
    await db.execute(
        update(ClickTransaction)
        .where(ClickTransaction.click_trans_id == int(key))
        .values(prepare_time=clock.now() - click_svc.PREPARE_TIMEOUT - timedelta(minutes=1))
    )
    await db.commit()


async def _click_read(db: AsyncSession, key: str) -> tuple[str, str]:
    stmt = (
        select(ClickTransaction)
        .where(ClickTransaction.click_trans_id == int(key))
        .execution_options(populate_existing=True)
    )
    txn = (await db.execute(stmt)).scalar_one()
    return txn.status, await _payment_status(db, txn.payment_id)


async def _payme_open(db: AsyncSession, number: str, amount: Decimal, key: str) -> None:
    await payme_svc.create_transaction(
        db,
        payme_id=key,
        time=payme_svc.now_ms() - _DAY_MS,  # Payme's creation time is the sweep's clock
        amount=int(amount * 100),
        account={"order": number},
    )
    await db.commit()


async def _payme_read(db: AsyncSession, key: str) -> tuple[str, str]:
    stmt = (
        select(PaymeTransaction)
        .where(PaymeTransaction.payme_id == key)
        .execution_options(populate_existing=True)
    )
    txn = (await db.execute(stmt)).scalar_one()
    return str(txn.state), await _payment_status(db, txn.payment_id)


async def _uzum_open(db: AsyncSession, number: str, amount: Decimal, key: str) -> None:
    await uzum_svc.create(
        db, service_id=101202, trans_id=key, account=number, amount=int(amount * 100)
    )
    await db.execute(
        update(UzumTransaction)
        .where(UzumTransaction.trans_id == key)
        .values(create_time=uzum_svc.now_ms() - _DAY_MS)
    )
    await db.commit()


async def _uzum_read(db: AsyncSession, key: str) -> tuple[str, str]:
    stmt = (
        select(UzumTransaction)
        .where(UzumTransaction.trans_id == key)
        .execution_options(populate_existing=True)
    )
    txn = (await db.execute(stmt)).scalar_one()
    return txn.status, await _payment_status(db, txn.payment_id)


KASSAS = [
    Kassa("click", _click_open, click_svc.cancel_stale, _click_read),
    Kassa("payme", _payme_open, payme_svc.cancel_stale, _payme_read),
    Kassa("uzum", _uzum_open, uzum_svc.fail_stale, _uzum_read),
]
#: The kassa row's status after the sweep released it.
SWEPT = {"click": "CANCELLED", "payme": "-1", "uzum": "FAILED"}
#: ... and while it still holds the attempt.
HELD = {"click": "PREPARED", "payme": "1", "uzum": "CREATED"}


async def _order_status(db: AsyncSession, order_id: str) -> str:
    stmt = select(Order.status).where(Order.id == order_id)
    return str((await db.execute(stmt)).scalar_one())


@pytest.fixture(params=KASSAS, ids=lambda k: k.name)
def kassa(request: pytest.FixtureRequest) -> Kassa:
    k: Kassa = request.param
    return k


async def test_a_stale_order_attempt_is_released_and_the_order_stays_pending(
    db_session: AsyncSession, kassa: Kassa
) -> None:
    order = await make_order(db_session, price_uzs=PRICE)
    await kassa.open_stale(db_session, order.number, PRICE, "7101")

    assert await kassa.sweep(db_session) == 1
    await db_session.commit()
    assert await kassa.read(db_session, "7101") == (SWEPT[kassa.name], "cancelled")
    assert await _order_status(db_session, order.id) == "pending"
    assert await kassa.sweep(db_session) == 0


async def test_a_topup_and_an_order_are_swept_in_one_pass(
    db_session: AsyncSession, kassa: Kassa
) -> None:
    topup = await make_topup(db_session, amount=Decimal(50000))
    order = await make_order(db_session, price_uzs=PRICE)
    await kassa.open_stale(db_session, topup.number, Decimal(50000), "7102")
    await kassa.open_stale(db_session, order.number, PRICE, "7103")

    assert await kassa.sweep(db_session) == 2
    await db_session.commit()
    for key in ("7102", "7103"):
        assert await kassa.read(db_session, key) == (SWEPT[kassa.name], "cancelled")
    await db_session.refresh(topup)
    assert (topup.status, await _order_status(db_session, order.id)) == ("pending", "pending")


async def test_the_scan_skips_an_order_a_callback_holds(
    db_session: AsyncSession, db_engine: AsyncEngine, kassa: Kassa
) -> None:
    """An order locked by an in-flight callback is skipped, not waited for; a top-up in the
    same pass is still swept, and the order's row waits for the next tick."""
    held = await make_order(db_session, price_uzs=PRICE)
    topup: WalletTopup = await make_topup(db_session, amount=Decimal(50000))
    await kassa.open_stale(db_session, held.number, PRICE, "7104")
    await kassa.open_stale(db_session, topup.number, Decimal(50000), "7105")

    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    async with factory() as holder, holder.begin():
        await resolve(holder, held.number, lock=True)
        async with factory() as sweeper:
            count = await asyncio.wait_for(kassa.sweep(sweeper), timeout=5)
            await sweeper.commit()
    assert count == 1
    assert await kassa.read(db_session, "7104") == (HELD[kassa.name], "pending")
    assert await kassa.read(db_session, "7105") == (SWEPT[kassa.name], "cancelled")
    assert await kassa.sweep(db_session) == 1
    await db_session.commit()
    assert await kassa.read(db_session, "7104") == (SWEPT[kassa.name], "cancelled")
