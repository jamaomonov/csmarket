"""Each kassa's money path holds over the limit and answers the kassa as paid; a kassa may
take a held payment back (spec 2026-10-21-payment-risk-limits, the R7 exception).

Request helpers are trimmed copies of ``test_click_webhook.py``, ``test_payme_service.py``,
``test_uzum_webhook.py`` and ``test_p2p_intake.py``. Every key, id and phone here is fake.
"""

from __future__ import annotations

import base64
import hashlib
import itertools
import uuid
from collections.abc import Awaitable, Callable, Iterator
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from csmarket.core import clock
from csmarket.core.config import get_settings
from csmarket.modules.p2p.models import P2PIncoming
from csmarket.modules.p2p.settings import load_settings
from csmarket.modules.payme import service as payme_svc
from csmarket.modules.payments.api import (
    WalletTopup,
    ensure_attempt,
    resolve,
    reverse,
    settle,
)
from csmarket.modules.risk.api import PaymentHold
from csmarket.modules.wallet.api import user_balance
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.orders_factory import make_order
from tests.integration.p2p_factory import make_card, p2p_on
from tests.integration.payments_factory import make_topup, make_user
from tests.integration.risk_factory import set_kassa_limit

pytestmark = pytest.mark.asyncio

Headers = Callable[[], Awaitable[dict[str, str]]]

TIYIN = 5_000_000  # the factory's 50 000 soʻm top-up, in tiyin
CLICK_SERVICE_ID, CLICK_SECRET = "108149", "fake-click-secret"
UZUM_SERVICE_ID = 101202
UZUM_LOGIN, UZUM_PASSWORD = "fake-uzum-sandbox", "fake-sandbox-password"
P2P_SECRET = "relay-secret-for-csmarket-0001"
HUMO, OWNER, CONNECTION = 900_000_001, 500_000_001, "conn-1"
_IDS: Iterator[int] = itertools.count(1)


@pytest.fixture(autouse=True)
def _kassa_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("CSMARKET_CLICK_MERCHANT_ID", "5000")
    monkeypatch.setenv("CSMARKET_CLICK_SERVICE_ID", CLICK_SERVICE_ID)
    monkeypatch.setenv("CSMARKET_CLICK_SECRET_KEY", CLICK_SECRET)
    monkeypatch.setenv("CSMARKET_UZUM_SERVICE_ID", str(UZUM_SERVICE_ID))
    monkeypatch.setenv("CSMARKET_UZUM_TEST_LOGIN", UZUM_LOGIN)
    monkeypatch.setenv("CSMARKET_UZUM_TEST_PASSWORD", UZUM_PASSWORD)
    monkeypatch.setenv("CSMARKET_P2P_WEBHOOK_SECRET", P2P_SECRET)
    get_settings.cache_clear()
    yield
    monkeypatch.undo()
    get_settings.cache_clear()


async def _holds(db: AsyncSession) -> list[PaymentHold]:
    db.expire_all()
    return list((await db.execute(select(PaymentHold))).scalars())


async def _assert_held_topup(db: AsyncSession, topup: WalletTopup) -> None:
    await db.refresh(topup)
    assert topup.status == "held"
    payment_id = topup.payment_id
    assert await user_balance(db, topup.user_id) == Decimal(0)
    holds = await _holds(db)
    assert [(h.kind, h.payment_id, h.decision) for h in holds] == [("topup", payment_id, None)]


# ---------- Payme ----------


async def _payme_create(db: AsyncSession, topup: WalletTopup, payme_id: str) -> dict[str, Any]:
    result = await payme_svc.create_transaction(
        db,
        payme_id=payme_id,
        time=payme_svc.now_ms() - 60_000,
        amount=TIYIN,
        account={"order": topup.number},
    )
    await db.commit()
    return dict(result)


async def _payme_perform(db: AsyncSession, payme_id: str) -> dict[str, Any]:
    result = await payme_svc.perform_transaction(db, payme_id=payme_id)
    await db.commit()
    return dict(result)


async def test_payme_perform_over_limit_answers_performed_and_holds(
    db_session: AsyncSession,
) -> None:
    """Payme PerformTransaction → state 2 in the answer; top-up held; balance 0; a later
    CancelTransaction takes it back (state −2) and closes the hold."""
    await set_kassa_limit(db_session, "payme", 1)
    topup = await make_topup(db_session)
    await _payme_create(db_session, topup, "pt-held")
    performed = await _payme_perform(db_session, "pt-held")
    assert performed["state"] == 2
    await _assert_held_topup(db_session, topup)

    cancelled = await payme_svc.cancel_transaction(db_session, payme_id="pt-held", reason=5)
    await db_session.commit()
    assert cancelled["state"] == -2
    await db_session.refresh(topup)
    assert topup.status == "reversed"
    assert await user_balance(db_session, topup.user_id) == Decimal(0)
    [hold] = await _holds(db_session)
    assert (hold.decision, hold.decided_by) == ("reversed_by_kassa", None)


async def test_payme_perform_retried_on_a_held_topup_answers_the_same_and_holds_once(
    db_session: AsyncSession,
) -> None:
    """Payme repeats PerformTransaction: the same state-2 answer, one hold, nothing credited."""
    await set_kassa_limit(db_session, "payme", 1)
    topup = await make_topup(db_session)
    await _payme_create(db_session, topup, "pt-held-retry")
    first = await _payme_perform(db_session, "pt-held-retry")
    second = await _payme_perform(db_session, "pt-held-retry")
    assert first == second
    assert first["state"] == 2
    await _assert_held_topup(db_session, topup)


# ---------- Click ----------


def _md5(*parts: str) -> str:
    return hashlib.md5("".join(parts).encode()).hexdigest()


def _click_body(trans_id: str, number: str, prepare_id: str | None = None) -> dict[str, str]:
    """A signed prepare (``prepare_id`` None) or complete body for 50 000 soʻm."""
    action = "0" if prepare_id is None else "1"
    at = "2026-10-01 10:00:00"
    middle = [] if prepare_id is None else [prepare_id]
    body = {
        "click_trans_id": trans_id,
        "service_id": CLICK_SERVICE_ID,
        "click_paydoc_id": "5001",
        "merchant_trans_id": number,
        "amount": "50000.00",
        "action": action,
        "error": "0",
        "error_note": "Success",
        "sign_time": at,
        "sign_string": _md5(
            trans_id, CLICK_SERVICE_ID, CLICK_SECRET, number, *middle, "50000.00", action, at
        ),
    }
    if prepare_id is not None:
        body["merchant_prepare_id"] = prepare_id
    return body


async def test_click_complete_over_limit_answers_success_and_holds(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Click prepare + complete → error 0; top-up held."""
    await set_kassa_limit(db_session, "click", 1)
    topup = await make_topup(db_session)
    prepared = (
        await integration_client.post(
            "/api/v1/payments/click/prepare", data=_click_body("9101", topup.number)
        )
    ).json()
    assert prepared["error"] == 0
    completed = (
        await integration_client.post(
            "/api/v1/payments/click/complete",
            data=_click_body("9101", topup.number, str(prepared["merchant_prepare_id"])),
        )
    ).json()
    assert (completed["error"], completed["error_note"]) == (0, "Success")
    await _assert_held_topup(db_session, topup)


# ---------- Uzum ----------


def _uzum_auth() -> dict[str, str]:
    raw = f"{UZUM_LOGIN}:{UZUM_PASSWORD}".encode()
    return {"Authorization": f"Basic {base64.b64encode(raw).decode()}"}


async def _uzum(client: AsyncClient, endpoint: str, body: dict[str, Any]) -> dict[str, Any]:
    r = await client.post(
        f"/api/v1/payments/uzum/{endpoint}",
        headers=_uzum_auth(),
        json={"serviceId": UZUM_SERVICE_ID, "timestamp": 1_790_000_000_000, **body},
    )
    assert r.status_code == 200, r.text
    payload: dict[str, Any] = r.json()
    return payload


async def test_uzum_confirm_over_limit_answers_confirmed_and_holds(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Uzum check + create + confirm → status CONFIRMED; top-up held; reverse → REVERSED."""
    await set_kassa_limit(db_session, "uzum", 1)
    topup = await make_topup(db_session)
    order = {"params": {"order": topup.number}}
    assert (await _uzum(integration_client, "check", order))["status"] == "OK"
    created = await _uzum(
        integration_client, "create", {**order, "transId": "uz-held", "amount": TIYIN}
    )
    assert created["status"] == "CREATED"
    confirmed = await _uzum(
        integration_client,
        "confirm",
        {
            "transId": "uz-held",
            "paymentSource": "UZCARD",
            "tariff": "003",
            "processingReferenceNumber": "000000",
            "phone": "998000000000",
            "cardType": 2,
        },
    )
    assert confirmed["status"] == "CONFIRMED"
    await _assert_held_topup(db_session, topup)

    reversed_ = await _uzum(integration_client, "reverse", {"transId": "uz-held"})
    assert reversed_["status"] == "REVERSED"
    await db_session.refresh(topup)
    assert topup.status == "reversed"
    [hold] = await _holds(db_session)
    assert hold.decision == "reversed_by_kassa"


# ---------- P2P ----------


def _humo_update(amount: str) -> dict[str, Any]:
    when = clock.now().astimezone(ZoneInfo("Asia/Tashkent"))
    text = (
        f"🎉 Пополнение\n➕ {amount} UZS\n📍 UB P2P Uzcard2Humo>T\n"
        f"💳 HUMOCARD *4321\n🕓 {when:%H:%M %d.%m.%Y}\n💰 1.000.000,00 UZS"
    )
    msg = {
        "message_id": next(_IDS),
        "business_connection_id": CONNECTION,
        "from": {"id": HUMO},
        "chat": {"id": HUMO},
        "text": text,
    }
    return {"update_id": next(_IDS), "business_message": msg}


async def test_p2p_matched_transfer_over_limit_is_held(
    integration_client: AsyncClient, db_session: AsyncSession, customer_headers: Headers
) -> None:
    """A parsed HUMO credit matching an open request settles into held, not credited."""
    await p2p_on(db_session)
    await make_card(db_session)
    s = await load_settings(db_session)
    s.humo_bot_user_id, s.owner_telegram_user_id, s.business_connection_id = (
        HUMO,
        OWNER,
        CONNECTION,
    )
    await db_session.commit()
    await set_kassa_limit(db_session, "p2p", 1)
    h = await customer_headers()
    r = await integration_client.post(
        "/api/v1/wallet/topups",
        json={"amount_uzs": 100_000, "provider": "p2p", "locale": "ru"},
        headers={**h, "Idempotency-Key": f"p2p-{uuid.uuid4()}"},
    )
    assert r.status_code == 201, r.text
    number = r.json()["number"]

    posted = await integration_client.post(
        "/api/v1/webhooks/telegram/p2p",
        json=_humo_update("100.000,00"),
        headers={"X-Telegram-Bot-Api-Secret-Token": P2P_SECRET},
    )
    assert posted.status_code == 200
    db_session.expire_all()
    topup = await db_session.scalar(select(WalletTopup).where(WalletTopup.number == number))
    assert topup is not None
    await _assert_held_topup(db_session, topup)
    rows = list((await db_session.execute(select(P2PIncoming))).scalars())
    assert [row.result for row in rows] == ["matched"]


# ---------- a kassa reversing a held payment ----------


async def test_kassa_reversal_of_held_topup_debits_nothing(db_session: AsyncSession) -> None:
    await set_kassa_limit(db_session, "payme", 1)
    user = await make_user(db_session)
    t = await make_topup(db_session, user=user, amount=Decimal(50_000))
    p = await ensure_attempt(
        db_session, payable=await resolve(db_session, t.number, lock=True), provider="payme"
    )
    await db_session.commit()
    await settle(db_session, payment=p, event_id="e1")
    await db_session.commit()
    await reverse(db_session, payment=p, event_id="r1")
    await db_session.commit()
    await db_session.refresh(t)
    hold = await db_session.scalar(select(PaymentHold).where(PaymentHold.payment_id == p.id))
    assert (t.status, p.status) == ("reversed", "refunded")
    assert p.extra_metadata["reverse_event_id"] == "r1"
    assert hold is not None
    assert (hold.decision, hold.decided_by) == ("reversed_by_kassa", None)
    assert hold.decided_at is not None
    assert await user_balance(db_session, user.id) == Decimal(0)

    await reverse(db_session, payment=p, event_id="r2")  # a replayed reversal is a no-op
    await db_session.commit()
    assert p.extra_metadata["reverse_event_id"] == "r1"


async def test_kassa_reversal_of_held_order_cancels_it(db_session: AsyncSession) -> None:
    await set_kassa_limit(db_session, "payme", 1)
    order = await make_order(db_session)
    p = await ensure_attempt(
        db_session, payable=await resolve(db_session, order.number, lock=True), provider="payme"
    )
    await db_session.commit()
    await settle(db_session, payment=p, event_id="e1")
    await db_session.commit()
    await reverse(db_session, payment=p, event_id="r1")
    await db_session.commit()
    await db_session.refresh(order)
    assert (order.status, p.status) == ("cancelled", "refunded")
    assert order.cancelled_at is not None
    n_open = await db_session.scalar(
        select(func.count()).select_from(PaymentHold).where(PaymentHold.decision.is_(None))
    )
    assert n_open == 0
