"""USD purchase debit and refund (plan B, spec §3, §6)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from csmarket.modules.wallet.api import (
    InsufficientBalanceError,
    admin_adjust_usd,
    credit_order_refund_usd,
    debit_purchase_usd,
    user_balance,
    user_usd_balance,
)
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.payments_factory import make_user

ADMIN = "00000000-0000-4000-8000-000000000001"
ORDER = "00000000-0000-4000-8000-0000000000a1"


async def _funded(db: AsyncSession, units: int) -> str:
    user = await make_user(db)
    await admin_adjust_usd(
        db,
        user_id=user.id,
        amount=Decimal(units),
        reason="seed",
        admin_id=ADMIN,
        idempotency_key=f"seed-usd-{user.id}",
    )
    await db.commit()
    return user.id


async def test_debit_then_refund_in_dollars(db_session: AsyncSession) -> None:
    uid = await _funded(db_session, 20_000)
    await debit_purchase_usd(db_session, user_id=uid, order_id=ORDER, units=Decimal(12_345))
    assert await user_usd_balance(db_session, uid) == Decimal(7_655)
    again = await debit_purchase_usd(db_session, user_id=uid, order_id=ORDER, units=Decimal(12_345))
    assert again.idempotency_key == f"purchase:order:{ORDER}"
    assert await user_usd_balance(db_session, uid) == Decimal(7_655)
    await credit_order_refund_usd(db_session, user_id=uid, order_id=ORDER, units=Decimal(12_345))
    assert await user_usd_balance(db_session, uid) == Decimal(20_000)
    assert await user_balance(db_session, uid) == Decimal(0)


async def test_short_usd_balance_books_nothing(db_session: AsyncSession) -> None:
    uid = await _funded(db_session, 1_000)
    with pytest.raises(InsufficientBalanceError):
        await debit_purchase_usd(db_session, user_id=uid, order_id=ORDER, units=Decimal(1_001))
    assert await user_usd_balance(db_session, uid) == Decimal(1_000)
