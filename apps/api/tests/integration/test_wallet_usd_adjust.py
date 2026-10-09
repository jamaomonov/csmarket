"""``admin_adjust_usd``: credit, clawback, never below zero, one post per key; the soʻm wallet
is untouched."""

from __future__ import annotations

from decimal import Decimal

import pytest
from csmarket.core.errors import ConflictError
from csmarket.modules.wallet.api import (
    InsufficientBalanceError,
    admin_adjust_usd,
    entries_for_admin,
    user_balance,
    user_usd_balance,
)
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.payments_factory import make_user

ADMIN_ID = "00000000-0000-4000-8000-000000000001"


async def _adjust(db: AsyncSession, user_id: str, units: int, key: str) -> None:
    await admin_adjust_usd(
        db,
        user_id=user_id,
        amount=Decimal(units),
        reason="yupay prepay",
        admin_id=ADMIN_ID,
        idempotency_key=key,
    )


async def test_credit_then_clawback_in_dollars(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    await _adjust(db_session, user.id, 250_000, "usd-adjust-credit-0001")
    await _adjust(db_session, user.id, -50_000, "usd-adjust-claw-00001")
    await db_session.commit()
    assert await user_usd_balance(db_session, user.id) == Decimal(200_000)
    assert await user_balance(db_session, user.id) == Decimal(0)
    lines = await entries_for_admin(db_session, user.id, limit=10, currency="USD")
    assert [(e.kind, e.amount) for e in lines] == [
        ("admin_adjust_usd", Decimal(-50_000)),
        ("admin_adjust_usd", Decimal(250_000)),
    ]


async def test_clawback_below_zero_is_refused(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    with pytest.raises(InsufficientBalanceError):
        await _adjust(db_session, user.id, -1, "usd-adjust-claw-00002")


async def test_a_key_reused_for_another_amount_is_409(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    await _adjust(db_session, user.id, 1000, "usd-adjust-same-key-01")
    with pytest.raises(ConflictError):
        await _adjust(db_session, user.id, 2000, "usd-adjust-same-key-01")
