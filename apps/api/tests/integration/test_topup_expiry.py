"""The top-up expiry sweep (ruling R8, Review Focus 3)."""

from __future__ import annotations

from datetime import timedelta

from csmarket.core import clock
from csmarket.modules.payments.hooks import ensure_attempt, mark_pending
from csmarket.modules.payments.models import Payment, WalletTopup
from csmarket.modules.payments.payable import resolve
from csmarket.modules.payments.topups import expire_stale
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.integration.payments_factory import make_topup


async def _open(db: AsyncSession, t: WalletTopup, provider: str) -> Payment:
    return await ensure_attempt(
        db, payable=await resolve(db, t.number, lock=True), provider=provider
    )


async def test_sweep_expires_only_untouched_topups(db_session: AsyncSession) -> None:
    stale = await make_topup(db_session, expires_at=clock.now() - timedelta(minutes=1))
    created = await _open(db_session, stale, "mock")
    bare = await make_topup(db_session, expires_at=clock.now() - timedelta(minutes=1))
    fresh = await make_topup(db_session)
    await _open(db_session, fresh, "mock")
    paid = await make_topup(
        db_session, status="succeeded", expires_at=clock.now() - timedelta(minutes=1)
    )
    await db_session.commit()
    assert await expire_stale(db_session) == 2
    await db_session.commit()
    for row in (stale, bare, fresh, paid, created):
        await db_session.refresh(row)
    assert (stale.status, bare.status, fresh.status, paid.status) == (
        "expired",
        "expired",
        "pending",
        "succeeded",
    )
    assert created.status == "cancelled"
    assert await expire_stale(db_session) == 0


async def test_sweep_keeps_a_topup_with_a_kassa_transaction(db_session: AsyncSession) -> None:
    held = await make_topup(db_session, expires_at=clock.now() - timedelta(minutes=1))
    a = await _open(db_session, held, "payme")
    await mark_pending(db_session, payment=a)
    # A sibling attempt nobody touched stays as it is too: the top-up is not expired.
    sibling = await _open(db_session, held, "mock")
    await db_session.commit()
    assert await expire_stale(db_session) == 0
    await db_session.commit()
    for row in (held, a, sibling):
        await db_session.refresh(row)
    assert (held.status, a.status, sibling.status) == ("pending", "pending", "created")


async def test_expired_topup_is_not_payable(db_session: AsyncSession) -> None:
    t = await make_topup(db_session, expires_at=clock.now() - timedelta(minutes=1))
    await expire_stale(db_session)
    await db_session.commit()
    await db_session.refresh(t)
    assert t.status == "expired"
    assert (await resolve(db_session, t.number)).reason == "expired"


async def test_sweep_honours_the_limit(db_session: AsyncSession) -> None:
    for _ in range(3):
        await make_topup(db_session, expires_at=clock.now() - timedelta(minutes=1))
    assert await expire_stale(db_session, limit=2) == 2
    await db_session.commit()
    assert await expire_stale(db_session, limit=2) == 1
    await db_session.commit()


async def test_sweep_skips_a_topup_a_kassa_is_holding(db_engine: AsyncEngine) -> None:
    """A kassa mid-create holds the top-up row: the sweep skips it rather than wait."""
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    async with factory() as setup:
        t = await make_topup(setup, expires_at=clock.now() - timedelta(minutes=1))
    async with factory() as kassa, factory() as sweeper:
        payable = await resolve(kassa, t.number, lock=True)
        assert await expire_stale(sweeper) == 0
        await sweeper.commit()
        attempt = await ensure_attempt(kassa, payable=payable, provider="payme")
        await mark_pending(kassa, payment=attempt)
        await kassa.commit()
        assert await expire_stale(sweeper) == 0
        await sweeper.commit()
    async with factory() as check:
        status = await check.scalar(select(WalletTopup.status).where(WalletTopup.id == t.id))
        assert status == "pending"
