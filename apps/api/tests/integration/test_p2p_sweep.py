"""``p2p.sweep``: a request past its ten minutes expires and keeps its amount quarantined; once
the quarantine ends the amount is free again and the unpaid attempt is cancelled."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import timedelta

from csmarket.modules.p2p.api import sweep
from csmarket.modules.p2p.models import P2PReservation
from csmarket.modules.payments.models import Payment
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.p2p_factory import make_card, p2p_on

Headers = Callable[[], Awaitable[dict[str, str]]]


async def test_expire_quarantine_then_release(
    integration_client: AsyncClient, db_session: AsyncSession, customer_headers: Headers
) -> None:
    await p2p_on(db_session)
    await make_card(db_session)
    r = await integration_client.post(
        "/api/v1/wallet/topups",
        json={"amount_uzs": 100_000, "provider": "p2p", "locale": "ru"},
        headers={**(await customer_headers()), "Idempotency-Key": f"p2p-{uuid.uuid4()}"},
    )
    assert r.status_code == 201, r.text
    row = await db_session.scalar(select(P2PReservation))
    assert row is not None
    expires = row.expires_at

    result = await sweep(db_session, at=expires + timedelta(seconds=1))
    await db_session.commit()
    db_session.expire_all()
    row = await db_session.scalar(select(P2PReservation))
    assert row is not None
    assert (result.expired, row.status, row.holds_amount) == (1, "expired", True)

    result = await sweep(db_session, at=expires + timedelta(minutes=10, seconds=1))
    await db_session.commit()
    db_session.expire_all()
    row = await db_session.scalar(select(P2PReservation))
    assert row is not None
    assert (result.released, row.holds_amount) == (1, False)
    payment = await db_session.get(Payment, row.payment_id)
    assert payment is not None
    assert payment.status == "cancelled"
