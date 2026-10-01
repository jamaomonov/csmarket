"""``/api/v1/wallet`` — balance and the customer's entries (Task 4)."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from decimal import Decimal

from csmarket.modules.payments.hooks import ensure_attempt, settle
from csmarket.modules.payments.payable import resolve
from csmarket.modules.users.models import User
from csmarket.modules.wallet.api import (
    Leg,
    Reference,
    ensure_account,
    post,
    user_account,
)
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.conftest import CUSTOMER_STEAM_ID
from tests.integration.payments_factory import make_topup

Headers = Callable[[], Awaitable[dict[str, str]]]


async def _customer(db: AsyncSession) -> User:
    user = await db.scalar(select(User).where(User.steam_id == CUSTOMER_STEAM_ID))
    assert user is not None
    return user


async def _dev_paid_topup(c: AsyncClient, h: dict[str, str], amount: int = 50000) -> str:
    r = await c.post(
        "/api/v1/wallet/topups",
        json={"amount_uzs": amount, "provider": "mock", "locale": "ru"},
        headers={**h, "Idempotency-Key": f"k-{uuid.uuid4()}"},
    )
    assert r.status_code == 201, r.text
    number: str = r.json()["number"]
    paid = await c.post(f"/api/v1/dev/topups/{number}/pay", headers=h)
    assert paid.status_code == 200, paid.text
    return number


async def test_a_new_user_has_a_zero_balance_and_no_entries(
    integration_client: AsyncClient, customer_headers: Headers
) -> None:
    h = await customer_headers()
    assert (await integration_client.get("/api/v1/wallet", headers=h)).json() == {
        "balance_uzs": "0"
    }
    entries = await integration_client.get("/api/v1/wallet/entries", headers=h)
    assert entries.json() == {"items": [], "next_cursor": None}


async def test_entries_show_a_paid_topup(
    integration_client: AsyncClient, customer_headers: Headers
) -> None:
    h = await customer_headers()
    number = await _dev_paid_topup(integration_client, h)
    assert (await integration_client.get("/api/v1/wallet", headers=h)).json() == {
        "balance_uzs": "50000"
    }
    body = (await integration_client.get("/api/v1/wallet/entries", headers=h)).json()
    assert body["next_cursor"] is None
    (entry,) = body["items"]
    assert set(entry) == {"id", "kind", "amount_uzs", "created_at", "reference_number"}
    assert (entry["kind"], entry["amount_uzs"], entry["reference_number"]) == (
        "topup",
        "+50000",
        number,
    )


async def test_a_debit_is_signed_minus_and_carries_no_actor_or_metadata(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    h = await customer_headers()
    await _dev_paid_topup(integration_client, h)
    user = await _customer(db_session)
    wallet = await user_account(db_session, user.id)
    house = await ensure_account(
        db_session, owner_type="house", owner_id="house", kind="house_adjustments"
    )
    await post(
        db_session,
        kind="admin_adjust",
        legs=[Leg(house.id, "D", Decimal(10000)), Leg(wallet.id, "C", Decimal(10000))],
        idempotency_key="admin_adjust:test-clawback",
        reference=Reference(type="admin", id="secret-admin-id"),
        actor="admin:secret-admin-id",
        metadata={"reason": "a private note"},
    )
    await db_session.commit()
    r = await integration_client.get("/api/v1/wallet/entries", headers=h)
    newest = r.json()["items"][0]
    assert (newest["kind"], newest["amount_uzs"], newest["reference_number"]) == (
        "admin_adjust",
        "-10000",
        None,
    )
    assert "secret-admin-id" not in r.text
    assert "a private note" not in r.text
    assert (await integration_client.get("/api/v1/wallet", headers=h)).json() == {
        "balance_uzs": "40000"
    }


async def test_keyset_paging_is_stable_without_duplicates(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    h = await customer_headers()
    user = await _customer(db_session)
    numbers: list[str] = []
    for i in range(30):
        t = await make_topup(db_session, user=user, amount=Decimal(1000 + i))
        numbers.append(t.number)
        p = await ensure_attempt(
            db_session, payable=await resolve(db_session, t.number, lock=True), provider="mock"
        )
        await settle(db_session, payment=p, event_id=f"e{i}")
        await db_session.commit()
    seen: list[dict[str, str]] = []
    cursor: str | None = None
    pages = 0
    while True:
        params: dict[str, str | int] = {"limit": 10}
        if cursor is not None:
            params["cursor"] = cursor
        page = (
            await integration_client.get("/api/v1/wallet/entries", params=params, headers=h)
        ).json()
        pages += 1
        seen.extend(page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
        assert pages < 5
    assert pages == 3
    assert len(seen) == 30
    assert len({e["id"] for e in seen}) == 30
    # Newest first: the last top-up paid is the first entry.
    assert [e["reference_number"] for e in seen] == list(reversed(numbers))
    assert seen[0]["amount_uzs"] == "+1029"


async def test_paging_limits_and_a_bad_cursor(
    integration_client: AsyncClient, customer_headers: Headers
) -> None:
    h = await customer_headers()
    for bad in ({"limit": 0}, {"limit": 101}, {"cursor": "%%%not-a-cursor"}):
        r = await integration_client.get("/api/v1/wallet/entries", params=bad, headers=h)
        assert r.status_code == 422, (bad, r.text)


async def test_another_user_sees_nothing(
    integration_client: AsyncClient, customer_headers: Headers, admin_headers: Headers
) -> None:
    await _dev_paid_topup(integration_client, await customer_headers())
    other = await admin_headers()
    assert (await integration_client.get("/api/v1/wallet", headers=other)).json() == {
        "balance_uzs": "0"
    }
    entries = (await integration_client.get("/api/v1/wallet/entries", headers=other)).json()
    assert entries == {"items": [], "next_cursor": None}


async def test_anonymous_is_401(integration_client: AsyncClient) -> None:
    assert (await integration_client.get("/api/v1/wallet")).status_code == 401
    assert (await integration_client.get("/api/v1/wallet/entries")).status_code == 401


async def test_entries_cost_the_same_queries_for_any_page_size(db_session: AsyncSession) -> None:
    """No N+1: the account, the page and one batch of top-up numbers (AGENTS §11)."""
    from csmarket.modules.wallet.api import entries_for_user
    from sqlalchemy import event

    from tests.integration.payments_factory import make_user

    async def _queries(paid: int) -> int:
        user = await make_user(db_session)
        for i in range(paid):
            t = await make_topup(db_session, user=user, amount=Decimal(1000 + i))
            p = await ensure_attempt(
                db_session, payable=await resolve(db_session, t.number, lock=True), provider="mock"
            )
            await settle(db_session, payment=p, event_id=f"q{i}")
            await db_session.commit()
        statements: list[str] = []

        def _capture(*args: object) -> None:
            statements.append(str(args[2]))

        engine = db_session.bind.sync_engine  # type: ignore[union-attr]
        event.listen(engine, "before_cursor_execute", _capture)
        try:
            page = await entries_for_user(db_session, user.id, limit=100)
        finally:
            event.remove(engine, "before_cursor_execute", _capture)
        assert len(page.items) == paid
        return len(statements)

    assert await _queries(2) == await _queries(12) == 3


async def test_order_numbers_cost_one_query_for_any_page_size(db_session: AsyncSession) -> None:
    """Top-ups and orders on one page: the account, the page, one batch per kind."""
    from csmarket.core.ids import new_id
    from csmarket.modules.wallet.api import credit_topup, debit_purchase, entries_for_user
    from sqlalchemy import event

    from tests.integration.orders_factory import make_order
    from tests.integration.payments_factory import make_user

    async def _queries(orders: int) -> int:
        user = await make_user(db_session)
        await credit_topup(
            db_session, user_id=user.id, topup_id=new_id(), amount=Decimal(10**7), provider="mock"
        )
        numbers = []
        for _ in range(orders):
            order = await make_order(db_session, user=user, status="paid", paid_with="wallet")
            await debit_purchase(
                db_session, user_id=user.id, order_id=order.id, amount=order.price_uzs
            )
            numbers.append(order.number)
        await db_session.commit()
        statements: list[str] = []

        def _capture(*args: object) -> None:
            statements.append(str(args[2]))

        engine = db_session.bind.sync_engine  # type: ignore[union-attr]
        event.listen(engine, "before_cursor_execute", _capture)
        try:
            page = await entries_for_user(db_session, user.id, limit=100)
        finally:
            event.remove(engine, "before_cursor_execute", _capture)
        purchases = [e for e in page.items if e.kind == "purchase"]
        assert sorted(e.reference_number or "" for e in purchases) == sorted(numbers)
        return len(statements)

    assert await _queries(1) == await _queries(6) == 4
