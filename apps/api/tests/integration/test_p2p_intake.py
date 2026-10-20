"""The P2P webhook (spec 2026-10-19-p2p-topup): HUMO notifications through the relay settle
the matching top-up once; everything else is journaled and left alone."""

from __future__ import annotations

import itertools
import uuid
from collections.abc import Awaitable, Callable, Iterator
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from csmarket.core import clock
from csmarket.core import config as cfg
from csmarket.modules.p2p.models import P2PCard, P2PIncoming, P2PReservation
from csmarket.modules.p2p.settings import load_settings
from csmarket.modules.payments.api import WalletTopup
from httpx import AsyncClient, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.p2p_factory import make_card, p2p_on

Headers = Callable[[], Awaitable[dict[str, str]]]
URL = "/api/v1/webhooks/telegram/p2p"
SECRET = "relay-secret-for-csmarket-0001"
HUMO = 900_000_001
OWNER = 500_000_001
CONNECTION = "conn-1"
TASHKENT = ZoneInfo("Asia/Tashkent")
_IDS: Iterator[int] = itertools.count(1)


@pytest.fixture(autouse=True)
def _secret(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("CSMARKET_P2P_WEBHOOK_SECRET", SECRET)
    cfg.get_settings.cache_clear()
    yield
    cfg.get_settings.cache_clear()


async def _trust(db: AsyncSession) -> None:
    s = await load_settings(db)
    s.humo_bot_user_id, s.owner_telegram_user_id, s.business_connection_id = HUMO, OWNER, CONNECTION
    await db.commit()


def _text(amount: str, last4: str = "4321", at: datetime | None = None, sign: str = "➕") -> str:
    when = (at or clock.now()).astimezone(TASHKENT)
    return (
        f"🎉 Пополнение\n{sign} {amount} UZS\n📍 UB P2P Uzcard2Humo>T\n"
        f"💳 HUMOCARD *{last4}\n🕓 {when:%H:%M %d.%m.%Y}\n💰 1.000.000,00 UZS"
    )


def _update(text: str, **over: Any) -> dict[str, Any]:
    msg: dict[str, Any] = {
        "message_id": next(_IDS),
        "business_connection_id": CONNECTION,
        "from": {"id": HUMO},
        "chat": {"id": HUMO},
        "text": text,
        **over,
    }
    return {"update_id": next(_IDS), "business_message": msg}


async def _post(c: AsyncClient, update: dict[str, Any], secret: str = SECRET) -> Response:
    return await c.post(URL, json=update, headers={"X-Telegram-Bot-Api-Secret-Token": secret})


async def _request(c: AsyncClient, h: dict[str, str], amount: int = 100_000) -> Any:
    r = await c.post(
        "/api/v1/wallet/topups",
        json={"amount_uzs": amount, "provider": "p2p", "locale": "ru"},
        headers={**h, "Idempotency-Key": f"p2p-{uuid.uuid4()}"},
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _topup(db: AsyncSession, number: str) -> WalletTopup:
    db.expire_all()
    found = await db.scalar(select(WalletTopup).where(WalletTopup.number == number))
    assert found is not None
    return found


async def _world(db: AsyncSession) -> None:
    await p2p_on(db)
    await make_card(db)
    await _trust(db)


async def test_a_wrong_secret_is_refused_before_anything_is_journaled(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    await _world(db_session)
    r = await _post(integration_client, _update(_text("100.000,00")), secret="nope")
    assert r.status_code == 401
    assert await db_session.scalar(select(P2PIncoming.id)) is None


async def test_an_exact_transfer_credits_once_even_when_redelivered(
    integration_client: AsyncClient, db_session: AsyncSession, customer_headers: Headers
) -> None:
    await _world(db_session)
    h = await customer_headers()
    t = await _request(integration_client, h)
    update = _update(_text("100.000,00"))
    for _ in range(2):  # the relay retries; both sides dedupe by message id
        assert (await _post(integration_client, update)).status_code == 200
    topup = await _topup(db_session, t["number"])
    assert topup.status == "succeeded"
    balance = (await integration_client.get("/api/v1/wallet", headers=h)).json()
    assert balance["balance_uzs"] == "100000"
    rows = list((await db_session.execute(select(P2PIncoming))).scalars())
    assert [r.result for r in rows] == ["matched"]


async def test_a_transfer_to_a_card_that_is_not_ours_is_ignored(
    integration_client: AsyncClient, db_session: AsyncSession, customer_headers: Headers
) -> None:
    await _world(db_session)
    t = await _request(integration_client, await customer_headers())
    await _post(integration_client, _update(_text("100.000,00", last4="9999")))
    assert (await _topup(db_session, t["number"])).status == "pending"
    row = await db_session.scalar(select(P2PIncoming))
    assert row is not None
    assert row.result == "ignored"


async def test_another_sender_or_a_forward_is_dropped(
    integration_client: AsyncClient, db_session: AsyncSession, customer_headers: Headers
) -> None:
    await _world(db_session)
    await _request(integration_client, await customer_headers())
    text = _text("100.000,00")
    await _post(integration_client, _update(text, **{"from": {"id": 1}}))
    await _post(integration_client, _update(text, forward_origin={"type": "user"}))
    await _post(integration_client, _update(text, business_connection_id="someone-else"))
    assert await db_session.scalar(select(P2PIncoming.id)) is None


async def test_an_amount_with_tiyin_never_matches(
    integration_client: AsyncClient, db_session: AsyncSession, customer_headers: Headers
) -> None:
    await _world(db_session)
    t = await _request(integration_client, await customer_headers())
    await _post(integration_client, _update(_text("100.000,50")))
    assert (await _topup(db_session, t["number"])).status == "pending"
    row = await db_session.scalar(select(P2PIncoming))
    assert row is not None
    assert row.result == "unmatched"


async def test_a_late_transfer_within_quarantine_pays_its_own_request_only(
    integration_client: AsyncClient, db_session: AsyncSession, customer_headers: Headers
) -> None:
    await _world(db_session)
    t = await _request(integration_client, await customer_headers())
    request = await db_session.scalar(select(P2PReservation))
    assert request is not None
    sent_at = request.created_at + timedelta(minutes=9)  # on time at the bank
    clock.set_clock(lambda: request.expires_at + timedelta(minutes=3))  # delivered late
    try:
        request.status, request.quarantine_until = (
            "expired",
            request.expires_at + timedelta(minutes=10),
        )
        await db_session.commit()
        await _post(integration_client, _update(_text("100.000,00", at=sent_at)))
    finally:
        clock.reset_clock()
    assert (await _topup(db_session, t["number"])).status == "succeeded"


async def test_a_transfer_after_the_request_closed_is_unmatched(
    integration_client: AsyncClient, db_session: AsyncSession, customer_headers: Headers
) -> None:
    await _world(db_session)
    t = await _request(integration_client, await customer_headers())
    request = await db_session.scalar(select(P2PReservation))
    assert request is not None
    after = request.expires_at + timedelta(minutes=5)  # sent after the window closed
    await _post(integration_client, _update(_text("100.000,00", at=after)))
    assert (await _topup(db_session, t["number"])).status == "pending"
    row = await db_session.scalar(select(P2PIncoming))
    assert row is not None
    assert row.result == "unmatched"


async def test_an_open_request_still_settles_while_p2p_is_in_maintenance(
    integration_client: AsyncClient, db_session: AsyncSession, customer_headers: Headers
) -> None:
    await _world(db_session)
    t = await _request(integration_client, await customer_headers())
    from tests.integration.kassa_fee_factory import set_fees

    await set_fees(db_session, statuses={"p2p": "maintenance"})
    await _post(integration_client, _update(_text("100.000,00")))
    assert (await _topup(db_session, t["number"])).status == "succeeded"


async def test_the_owner_s_connection_is_pinned_from_a_business_connection_update(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    await p2p_on(db_session)
    s = await load_settings(db_session)
    s.humo_bot_user_id, s.owner_telegram_user_id = HUMO, OWNER
    await db_session.commit()
    update = {
        "update_id": next(_IDS),
        "business_connection": {"id": "conn-new", "user": {"id": OWNER}, "is_enabled": True},
    }
    assert (await _post(integration_client, update)).status_code == 200
    db_session.expire_all()
    assert (await load_settings(db_session)).business_connection_id == "conn-new"


async def test_a_transfer_whose_top_up_was_paid_another_way_stays_on_the_journal(
    integration_client: AsyncClient, db_session: AsyncSession, customer_headers: Headers
) -> None:
    await _world(db_session)
    t = await _request(integration_client, await customer_headers())
    topup = await _topup(db_session, t["number"])
    topup.status = "succeeded"  # paid through a kassa meanwhile (as settle would leave it)
    await db_session.commit()
    r = await _post(integration_client, _update(_text("100.000,00")))
    assert r.status_code == 200, r.text
    row = await db_session.scalar(select(P2PIncoming))
    assert row is not None
    assert row.result == "unmatched"  # money to resolve by hand, never lost


async def test_a_wrong_sized_body_is_413_before_it_is_read_whole(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    await _world(db_session)
    big = {"update_id": 1, "business_message": {"text": "x" * (70 * 1024)}}
    r = await _post(integration_client, big)
    assert r.status_code == 413


async def test_a_request_handed_out_is_paid_even_after_its_card_was_switched_off(
    integration_client: AsyncClient, db_session: AsyncSession, customer_headers: Headers
) -> None:
    """Review 2026-10-20: the buyer saw the number and transferred on time; an admin
    switching the card off in between must not strand the transfer as unmatched."""
    await _world(db_session)
    h = await customer_headers()
    t = await _request(integration_client, h)
    card = await db_session.scalar(select(P2PCard))
    assert card is not None
    card.active = False
    await db_session.commit()
    amount = f"{int(t['p2p']['amount_uzs']):,}".replace(",", ".") + ",00"
    r = await _post(integration_client, _update(_text(amount)))
    assert r.status_code == 200
    assert (await _topup(db_session, t["number"])).status == "succeeded"
