"""The admin releases a hold or records the money returned (spec 2026-10-21)."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from decimal import Decimal

import pytest
from csmarket.modules.admin.models import AdminAuditLog
from csmarket.modules.orders.api import Order
from csmarket.modules.payments.api import Payment, WalletTopup, ensure_attempt, resolve, settle
from csmarket.modules.payments.holds import open_counts
from csmarket.modules.payments.holds_admin import PAGE
from csmarket.modules.realtime.api import CHANNEL
from csmarket.modules.risk.api import PaymentHold
from csmarket.modules.users.api import User
from csmarket.modules.wallet.api import user_balance
from httpx import AsyncClient
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.integration.orders_factory import listen_channel, listen_orders, make_order
from tests.integration.payments_factory import make_topup, make_user
from tests.integration.risk_factory import set_kassa_limit

pytestmark = pytest.mark.asyncio
Headers = Callable[[], Awaitable[dict[str, str]]]
BASE = "/api/v1/admin/payments/holds"


def _key() -> dict[str, str]:
    return {"Idempotency-Key": f"admin-hold-{uuid.uuid4()}"}


async def _hold_of(db: AsyncSession, payment: Payment) -> PaymentHold:
    hold = await db.scalar(select(PaymentHold).where(PaymentHold.payment_id == payment.id))
    assert hold is not None
    return hold


async def _held_topup(
    db: AsyncSession, amount: int = 50_000
) -> tuple[User, WalletTopup, Payment, PaymentHold]:
    await set_kassa_limit(db, "payme", 1)
    user = await make_user(db)
    t = await make_topup(db, user=user, amount=Decimal(amount))
    p = await ensure_attempt(db, payable=await resolve(db, t.number, lock=True), provider="payme")
    await db.commit()
    await settle(db, payment=p, event_id="e1")
    await db.commit()
    return user, t, p, await _hold_of(db, p)


async def _held_order(db: AsyncSession) -> tuple[Order, Payment, PaymentHold]:
    await set_kassa_limit(db, "payme", 1)
    order = await make_order(db)
    p = await ensure_attempt(
        db, payable=await resolve(db, order.number, lock=True), provider="payme"
    )
    await db.commit()
    await settle(db, payment=p, event_id="e1")
    await db.commit()
    return order, p, await _hold_of(db, p)


async def test_list_open_holds(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    user, t, _, hold = await _held_topup(db_session)
    r = await integration_client.get(f"{BASE}?state=open", headers=await admin_headers())
    assert r.status_code == 200
    body = r.json()
    item = next(i for i in body["items"] if i["id"] == hold.id)
    assert (item["number"], item["kind"], item["reason"], item["amount_uzs"]) == (
        t.number,
        "topup",
        "kassa_limit",
        "50000",
    )
    assert (item["provider"], item["window_sum_uzs"], item["limit_uzs"]) == ("payme", "50000", "1")
    assert item["user"] == {"id": user.id, "display_name": user.display_name}
    assert (item["decision"], item["decided_by"], item["decided_at"]) == (None, None, None)
    assert body["next_cursor"] is None


async def test_decided_list_and_keyset_pages(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    holds = [(await _held_topup(db_session))[3] for _ in range(3)]
    h = await admin_headers()
    decided = holds[0]
    assert (
        await integration_client.post(f"{BASE}/{decided.id}/returned", headers={**h, **_key()})
    ).status_code == 200
    r = await integration_client.get(f"{BASE}?state=decided", headers=h)
    items = r.json()["items"]
    assert [i["id"] for i in items] == [decided.id]
    assert items[0]["decided_by"] is not None
    assert items[0]["decided_at"] is not None
    opened = (await integration_client.get(f"{BASE}?state=open", headers=h)).json()["items"]
    assert {i["id"] for i in opened} == {holds[1].id, holds[2].id}


async def test_open_list_pages_by_cursor(
    integration_client: AsyncClient,
    admin_headers: Headers,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("csmarket.modules.payments.holds_admin.PAGE", 2)
    ids = {(await _held_topup(db_session))[3].id for _ in range(3)}
    h = await admin_headers()
    first = (await integration_client.get(f"{BASE}?state=open", headers=h)).json()
    assert len(first["items"]) == 2
    assert first["next_cursor"] is not None
    second = (
        await integration_client.get(f"{BASE}?state=open&cursor={first['next_cursor']}", headers=h)
    ).json()
    assert len(second["items"]) == 1
    assert second["next_cursor"] is None
    assert {i["id"] for i in first["items"] + second["items"]} == ids
    assert PAGE == 50


async def test_list_query_count_is_constant(
    integration_client: AsyncClient,
    admin_headers: Headers,
    db_session: AsyncSession,
    db_engine: AsyncEngine,
) -> None:
    h = await admin_headers()

    async def _count(more: int) -> int:
        for _ in range(more):
            await _held_topup(db_session)
        statements: list[str] = []

        def _capture(*args: object) -> None:
            statements.append(str(args[2]))

        engine = db_engine.sync_engine
        event.listen(engine, "before_cursor_execute", _capture)
        try:
            r = await integration_client.get(f"{BASE}?state=open", headers=h)
        finally:
            event.remove(engine, "before_cursor_execute", _capture)
        assert r.status_code == 200
        return len(statements)

    few = await _count(1)
    assert few > 0
    assert few == await _count(4)


async def test_release_topup_credits_and_audits(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    user, t, _, hold = await _held_topup(db_session)
    r = await integration_client.post(
        f"{BASE}/{hold.id}/release", headers={**await admin_headers(), **_key()}
    )
    assert r.status_code == 200
    assert r.json()["decision"] == "released"
    await db_session.refresh(t)
    assert t.status == "succeeded"
    assert await user_balance(db_session, user.id) == Decimal(50_000)
    audit = await db_session.scalar(
        select(AdminAuditLog).where(AdminAuditLog.action == "payments.hold.release")
    )
    assert audit is not None
    assert (audit.target_type, audit.target_id) == ("payment_hold", hold.id)


async def test_release_order_marks_paid_and_notifies(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    order, _, hold = await _held_order(db_session)
    headers = {**await admin_headers(), **_key()}
    async with listen_orders() as heard:
        r = await integration_client.post(f"{BASE}/{hold.id}/release", headers=headers)
        assert await heard.drain() == [order.number]
    assert r.status_code == 200
    await db_session.refresh(order)
    assert order.status == "paid"
    assert order.paid_at is not None


async def test_returned_topup_credits_nothing(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    user, t, p, hold = await _held_topup(db_session)
    r = await integration_client.post(
        f"{BASE}/{hold.id}/returned", headers={**await admin_headers(), **_key()}
    )
    assert r.status_code == 200
    assert r.json()["decision"] == "returned"
    await db_session.refresh(t)
    await db_session.refresh(p)
    assert (t.status, p.status) == ("rejected", "refunded")
    assert await user_balance(db_session, user.id) == Decimal(0)
    audit = await db_session.scalar(
        select(AdminAuditLog).where(AdminAuditLog.action == "payments.hold.returned")
    )
    assert audit is not None


async def test_returned_order_is_cancelled_with_its_kassa_and_nudged(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    order, _, hold = await _held_order(db_session)
    headers = {**await admin_headers(), **_key()}
    async with listen_channel(CHANNEL) as events, listen_orders() as heard:
        r = await integration_client.post(f"{BASE}/{hold.id}/returned", headers=headers)
        assert await events.drain() == [f"{order.user_id}:{order.number}"]
        assert await heard.drain() == []
    assert r.status_code == 200
    await db_session.refresh(order)
    assert (order.status, order.paid_with, order.paid_at) == ("cancelled", "payme", None)


async def test_second_decision_is_refused(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    user, _, _, hold = await _held_topup(db_session)
    h = await admin_headers()
    assert (
        await integration_client.post(f"{BASE}/{hold.id}/release", headers={**h, **_key()})
    ).status_code == 200
    r = await integration_client.post(f"{BASE}/{hold.id}/returned", headers={**h, **_key()})
    assert r.status_code == 409
    assert r.json()["code"] == "hold_decided"
    assert await user_balance(db_session, user.id) == Decimal(50_000)


async def test_replay_returns_the_same_answer(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    user, _, _, hold = await _held_topup(db_session)
    h = {**await admin_headers(), **_key()}
    a = await integration_client.post(f"{BASE}/{hold.id}/release", headers=h)
    b = await integration_client.post(f"{BASE}/{hold.id}/release", headers=h)
    assert a.status_code == b.status_code == 200
    assert a.json() == b.json()
    assert await user_balance(db_session, user.id) == Decimal(50_000)


@pytest.mark.parametrize("hold_id", [str(uuid.uuid4()), "not-a-uuid"])
async def test_unknown_hold_is_404(
    integration_client: AsyncClient, admin_headers: Headers, hold_id: str
) -> None:
    r = await integration_client.post(
        f"{BASE}/{hold_id}/release", headers={**await admin_headers(), **_key()}
    )
    assert r.status_code == 404
    assert r.json()["code"] == "hold_not_found"


async def test_customer_cannot_list(
    integration_client: AsyncClient, customer_headers: Headers
) -> None:
    r = await integration_client.get(BASE, headers=await customer_headers())
    assert r.status_code == 403


async def test_open_counts_and_dashboard(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    await _held_topup(db_session)
    counts = await open_counts(db_session)
    assert counts["kassa_limit"] >= 1
    assert counts["check_failed"] == 0
    assert set(counts) == {"kassa_limit", "user_limit", "check_failed"}
    r = await integration_client.get(
        "/api/v1/admin/dashboard?days=1", headers=await admin_headers()
    )
    assert r.json()["holds_open"] >= 1
