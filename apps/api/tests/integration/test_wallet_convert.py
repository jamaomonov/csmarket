"""Converting soʻm into the USD wallet (spec 2026-10-09 §3)."""

from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest
from csmarket.core.errors import ConflictError, ValidationError
from csmarket.modules.wallet.api import (
    Conversion,
    InsufficientBalanceError,
    admin_adjust,
    convert_to_usd,
    usd_units_for,
    user_balance,
    user_usd_balance,
)
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.integration.payments_factory import make_user

RATE = Decimal("12777.01")  # CBU 12650.5 × 1.01
ADMIN = "00000000-0000-4000-8000-000000000001"


def test_units_round_down_to_a_tenth_of_a_cent() -> None:
    # 100 000 / 12 777.01 = 7.82656… $ → 7 826 units
    assert usd_units_for(Decimal(100_000), RATE) == Decimal(7826)
    assert usd_units_for(Decimal(12), RATE) == Decimal(0)


async def _funded(db: AsyncSession, soum: int) -> str:
    user = await make_user(db)
    await admin_adjust(
        db,
        user_id=user.id,
        amount=Decimal(soum),
        reason="seed",
        admin_id=ADMIN,
        idempotency_key=f"seed-{user.id}",
    )
    await db.commit()
    return user.id


async def _convert(db: AsyncSession, user_id: str, soum: int, key: str) -> Conversion:
    return await convert_to_usd(
        db,
        user_id=user_id,
        amount_uzs=Decimal(soum),
        rate=RATE,
        snapshot_id="00000000-0000-4000-8000-0000000000f1",
        idempotency_key=key,
    )


async def test_soum_out_dollars_in(db_session: AsyncSession) -> None:
    uid = await _funded(db_session, 150_000)
    conv = await _convert(db_session, uid, 100_000, "convert-key-000000001")
    await db_session.commit()
    assert (conv.amount_uzs, conv.usd_units, conv.rate) == (Decimal(100_000), Decimal(7826), RATE)
    assert await user_balance(db_session, uid) == Decimal(50_000)
    assert await user_usd_balance(db_session, uid) == Decimal(7826)


async def test_replay_returns_the_same_conversion(db_session: AsyncSession) -> None:
    uid = await _funded(db_session, 150_000)
    first = await _convert(db_session, uid, 100_000, "convert-key-000000002")
    again = await _convert(db_session, uid, 100_000, "convert-key-000000002")
    assert again.transaction_id == first.transaction_id
    assert await user_balance(db_session, uid) == Decimal(50_000)


async def test_same_key_other_amount_is_409(db_session: AsyncSession) -> None:
    uid = await _funded(db_session, 150_000)
    await _convert(db_session, uid, 100_000, "convert-key-000000003")
    with pytest.raises(ConflictError, match="Idempotency-Key"):
        await _convert(db_session, uid, 20_000, "convert-key-000000003")


async def test_more_than_the_balance_is_refused(db_session: AsyncSession) -> None:
    uid = await _funded(db_session, 50_000)
    with pytest.raises(InsufficientBalanceError):
        await _convert(db_session, uid, 50_001, "convert-key-000000004")


async def test_a_sum_under_one_unit_is_refused(db_session: AsyncSession) -> None:
    uid = await _funded(db_session, 50_000)
    with pytest.raises(ValidationError, match="too small"):
        await _convert(db_session, uid, 12, "convert-key-000000005")


async def test_two_at_once_never_overdraw(db_session: AsyncSession, db_engine: AsyncEngine) -> None:
    session_factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    uid = await _funded(db_session, 100_000)

    async def one(key: str) -> bool:
        async with session_factory() as db:
            try:
                await _convert(db, uid, 70_000, key)
            except InsufficientBalanceError:
                return False
            await db.commit()
            return True

    results = await asyncio.gather(one("convert-race-0000001"), one("convert-race-0000002"))
    assert sorted(results) == [False, True]
    assert await user_balance(db_session, uid) == Decimal(30_000)
