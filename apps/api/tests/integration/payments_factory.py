"""Rows for payments tests: a user and a top-up (shared by the M3 payments suites).

Import as ``from tests.integration.payments_factory import make_topup``.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from csmarket.core import clock
from csmarket.core.ids import new_id
from csmarket.core.numbers import allocate, topup_number
from csmarket.modules.payments.models import WalletTopup
from csmarket.modules.users.models import User
from sqlalchemy.ext.asyncio import AsyncSession


def fake_steam_id() -> str:
    """A steamid64-shaped id that belongs to nobody (fake, random)."""
    return "7656119" + "".join(secrets.choice("0123456789") for _ in range(10))


async def make_user(db: AsyncSession, sid: str | None = None) -> User:
    """A committed user with Steam id ``sid`` (random fake when omitted)."""
    user = User(id=new_id(), steam_id=sid or fake_steam_id())
    db.add(user)
    await db.commit()
    return user


async def make_topup(
    db: AsyncSession,
    *,
    user: User | None = None,
    amount: Decimal = Decimal(50000),
    status: str = "pending",
    expires_at: datetime | None = None,
) -> WalletTopup:
    """A committed top-up (a new user's unless ``user``), expiring in 30 min by default."""
    owner = user or await make_user(db)
    topup = WalletTopup(
        id=new_id(),
        number=await allocate(db, WalletTopup.number, topup_number),
        user_id=owner.id,
        amount_uzs=amount,
        status=status,
        idempotency_key=f"test-{uuid4()}",
        expires_at=expires_at or clock.now() + timedelta(minutes=30),
        succeeded_at=clock.now() if status == "succeeded" else None,
    )
    db.add(topup)
    await db.commit()
    return topup
