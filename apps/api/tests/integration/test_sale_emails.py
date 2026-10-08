"""Sale letters: one per sale and kind; rendered with the sale's link in the seller's locale."""

from __future__ import annotations

import json

import pytest
from csmarket.core import clock as core_clock
from csmarket.core.redis import get_redis
from csmarket.modules.notifications.dev_transport import DEV_MAIL_KEY, DevTransport
from csmarket.modules.notifications.models import EmailOutbox
from csmarket.modules.notifications.sender import drain_emails
from csmarket.modules.sales.letters import enqueue_sale_letter
from csmarket.modules.users.models import User
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.sales_factory import make_sale

pytestmark = pytest.mark.asyncio


async def test_a_replayed_event_enqueues_one_letter(db_session: AsyncSession) -> None:
    sale = await make_sale(db_session, status="hold")
    for _ in range(2):
        await enqueue_sale_letter(db_session, sale, "sale_hold")
        await db_session.commit()
    rows = (
        await db_session.scalars(select(EmailOutbox).where(EmailOutbox.sale_id == sale.id))
    ).all()
    assert [(r.kind, r.order_id, r.payload) for r in rows] == [
        ("sale_hold", None, {"number": sale.number, "amount_uzs": "155200"})
    ]


async def test_a_card_letter_carries_the_last_four_only(db_session: AsyncSession) -> None:
    sale = await make_sale(db_session, status="payout", payout_to="card")
    await enqueue_sale_letter(db_session, sale, "sale_paid", to="card", last4="9015")
    await db_session.commit()
    row = await db_session.scalar(select(EmailOutbox).where(EmailOutbox.sale_id == sale.id))
    assert row is not None
    assert row.payload == {
        "number": sale.number,
        "amount_uzs": "155200",
        "to": "card",
        "last4": "9015",
    }


@pytest.mark.parametrize("locale", ["ru", "uz", "en"])
async def test_the_drain_sends_it_with_the_sale_link(db_session: AsyncSession, locale: str) -> None:
    sale = await make_sale(db_session, status="hold")
    number = sale.number  # read before the commit expires the row
    await db_session.execute(
        update(User)
        .where(User.id == sale.user_id)
        .values(email="seller@example.test", email_verified_at=core_clock.now(), locale=locale)
    )
    await enqueue_sale_letter(db_session, sale, "sale_hold")
    await db_session.commit()
    assert await drain_emails(db_session, transport=DevTransport(get_redis())) == 1
    [letter] = [json.loads(x) for x in await get_redis().lrange(DEV_MAIL_KEY, 0, -1)]
    prefix = {"ru": "", "uz": "/uz", "en": "/en"}[locale]
    assert letter["kind"] == "sale_hold"
    assert f"{prefix}/account/sales/{number}" in letter["text"]
