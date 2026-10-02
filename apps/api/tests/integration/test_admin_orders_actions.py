"""Admin order actions: «Разобрано» (resolve), refund to the balance, retry the buy — audited,
idempotent, refused while a buy attempt holds the order (M4a Task 12, rulings R3, K, M)."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from csmarket.core import clock
from csmarket.modules.admin.models import AdminAuditLog
from csmarket.modules.orders.api import admin_refund, attempt_buy, can_refund, can_retry
from csmarket.modules.orders.buy_lease import release, take_lease
from csmarket.modules.orders.models import Order, SkinTrade
from csmarket.modules.users.models import User
from csmarket.modules.wallet.api import user_balance
from csmarket.modules.wallet.models import WalletTransaction
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.integration.conftest import ADMIN_STEAM_ID
from tests.integration.fake_trade_client import FakeTradeClient, waxpeer_trade
from tests.integration.orders_factory import make_order, make_trade
from tests.integration.trade_sweeps_kit import load, reconcile_once, sweep_settings

Headers = Callable[[], Awaitable[dict[str, str]]]
PRICE = Decimal(171_800)
BASE = "/api/v1/admin/orders"


def _key() -> dict[str, str]:
    return {"Idempotency-Key": f"admin-orders-{uuid.uuid4()}"}


async def _order(
    db: AsyncSession, *, status: str = "buying", trade: dict[str, Any] | None = None, **over: Any
) -> Order:
    """A committed payme-paid order and, unless ``trade`` is ``None``, its trade."""
    order = await make_order(
        db, status=status, paid_with="payme", paid_at=clock.now(), price_uzs=PRICE, **over
    )
    if trade is not None:
        await make_trade(db, order, **trade)
    return order


def _attention(reason: str, *, resolved: bool, **more: Any) -> dict[str, Any]:
    return {
        "attention_reason": reason,
        "resolved_at": clock.now() - timedelta(minutes=1) if resolved else None,
        "resolved_by": "an-earlier-admin" if resolved else None,
        **more,
    }


async def _admin_id(db: AsyncSession) -> str:
    admin = await db.scalar(select(User).where(User.steam_id == ADMIN_STEAM_ID))
    assert admin is not None
    return admin.id


async def _audit(db: AsyncSession, action: str) -> list[AdminAuditLog]:
    rows = await db.scalars(select(AdminAuditLog).where(AdminAuditLog.action == action))
    return list(rows)


async def _refunds(db: AsyncSession, order: Order) -> int:
    rows = await db.scalars(
        select(WalletTransaction).where(
            WalletTransaction.kind == "refund", WalletTransaction.reference_id == order.id
        )
    )
    return len(list(rows))


async def _post(
    client: AsyncClient,
    h: dict[str, str],
    order: Order,
    action: str,
    *,
    body: dict[str, Any] | None = None,
    key: dict[str, str] | None = None,
) -> tuple[int, dict[str, Any]]:
    r = await client.post(
        f"{BASE}/{order.number}/{action}", json=body, headers={**h, **(key or _key())}
    )
    return r.status_code, r.json()


# --- resolve ----------------------------------------------------------------------------


async def test_resolve_stamps_once_and_is_audited(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    h = await admin_headers()
    admin = await _admin_id(db_session)
    order = await _order(db_session, trade=_attention("buy_unconfirmed", resolved=False))
    key = _key()
    status, body = await _post(
        integration_client, h, order, "resolve", body={"note": "  no trade in Waxpeer  "}, key=key
    )
    assert status == 200, body
    t = body["trade"]
    assert (t["resolved_by"], t["resolved_note"]) == (admin, "no trade in Waxpeer")
    assert t["resolved_at"] is not None
    assert body["can_refund"] is True
    (row,) = await _audit(db_session, "orders.trade.resolve")
    assert (row.actor_user_id, row.target_type, row.target_id) == (admin, "order", order.number)
    assert row.payload == {"reason": "buy_unconfirmed"}

    # The same key replays the stored page; another key leaves the stamp as it was.
    again = await _post(
        integration_client, h, order, "resolve", body={"note": "  no trade in Waxpeer  "}, key=key
    )
    assert again == (200, body)
    status, later = await _post(integration_client, h, order, "resolve", body={"note": "other"})
    assert status == 200
    assert later["trade"]["resolved_note"] == "no trade in Waxpeer"
    assert later["trade"]["resolved_at"] == t["resolved_at"]
    assert len(await _audit(db_session, "orders.trade.resolve")) == 1
    mismatch = await _post(integration_client, h, order, "resolve", body={"note": "x"}, key=key)
    assert (mismatch[0], mismatch[1]["code"]) == (409, "idempotency_mismatch")


async def test_resolve_without_a_note_and_with_an_empty_one(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    h = await admin_headers()
    for body in ({}, {"note": None}, {"note": "   "}):
        order = await _order(db_session, trade=_attention("ambiguous_trade", resolved=False))
        status, page = await _post(integration_client, h, order, "resolve", body=body)
        assert status == 200, page
        assert page["trade"]["resolved_note"] is None
        assert page["trade"]["resolved_at"] is not None


async def test_resolve_with_nothing_to_resolve_is_409(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    h = await admin_headers()
    no_trade = await _order(db_session, status="paid")
    calm = await _order(db_session, trade={"status": 0})
    for order in (no_trade, calm):
        status, body = await _post(integration_client, h, order, "resolve", body={})
        assert (status, body["code"]) == (409, "nothing_to_resolve")
    assert await _audit(db_session, "orders.trade.resolve") == []


@pytest.mark.parametrize(
    ("body", "headers"),
    [
        ({"note": "x" * 501}, None),
        ({"note": "ok", "extra": 1}, None),
        ({"note": "ok"}, {}),
        ({"note": "ok"}, {"Idempotency-Key": "short"}),
    ],
)
async def test_resolve_refuses_a_bad_body_or_key(
    integration_client: AsyncClient,
    admin_headers: Headers,
    db_session: AsyncSession,
    body: dict[str, Any],
    headers: dict[str, str] | None,
) -> None:
    h = await admin_headers()
    order = await _order(db_session, trade=_attention("buy_unconfirmed", resolved=False))
    r = await integration_client.post(
        f"{BASE}/{order.number}/resolve",
        json=body,
        headers={**h, **(_key() if headers is None else headers)},
    )
    assert r.status_code == 422, r.text


# --- refund -----------------------------------------------------------------------------


async def test_admin_refund_of_attention_order_needs_resolve(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    h = await admin_headers()
    order = await _order(
        db_session,
        trade=_attention("buy_unconfirmed", resolved=False, buy_unconfirmed_at=clock.now()),
    )
    status, body = await _post(integration_client, h, order, "refund")
    assert (status, body["code"]) == (409, "order_in_flight")
    assert await _refunds(db_session, order) == 0

    status, page = await _post(integration_client, h, order, "resolve", body={"note": "not bought"})
    assert (status, page["can_refund"], page["can_retry"]) == (200, True, True)

    key = _key()
    status, page = await _post(integration_client, h, order, "refund", key=key)
    assert status == 200, page
    assert (page["order"]["status"], page["order"]["failure_reason"]) == ("failed", "admin")
    assert page["order"]["refunded_to"] == "balance"
    assert (page["can_refund"], page["can_retry"]) == (False, False)
    assert page["trade"]["buy_pending"] is False
    assert await user_balance(db_session, order.user_id) == PRICE
    (row,) = await _audit(db_session, "orders.refund")
    assert (row.target_type, row.target_id, row.payload) == (
        "order",
        order.number,
        {"amount_uzs": 171800},
    )

    replay = await _post(integration_client, h, order, "refund", key=key)
    assert replay == (200, page)
    assert await _refunds(db_session, order) == 1
    assert len(await _audit(db_session, "orders.refund")) == 1
    status, body = await _post(integration_client, h, order, "refund")
    assert (status, body["code"]) == (409, "already_refunded")
    assert await user_balance(db_session, order.user_id) == PRICE


@pytest.mark.parametrize(
    ("order_status", "trade", "code"),
    [
        ("trade_sent", {"status": 4}, "order_in_flight"),
        ("buying", _attention("rolled_back", resolved=True), "order_in_flight"),
        ("delivered", {"status": 5}, "order_not_refundable"),
        ("pending", None, "order_not_refundable"),
    ],
)
async def test_refund_refusals_write_nothing(
    *,
    integration_client: AsyncClient,
    admin_headers: Headers,
    db_session: AsyncSession,
    order_status: str,
    trade: dict[str, Any] | None,
    code: str,
) -> None:
    h = await admin_headers()
    order = await _order(db_session, status=order_status, trade=trade)
    status, body = await _post(integration_client, h, order, "refund")
    assert (status, body["code"]) == (409, code)
    assert await _refunds(db_session, order) == 0
    assert await _audit(db_session, "orders.refund") == []


# --- retry ------------------------------------------------------------------------------


async def test_retry_clears_attention_and_the_next_reconcile_adopts_without_buying(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    h = await admin_headers()
    order = await _order(
        db_session,
        trade=_attention(
            "buy_unconfirmed", resolved=True, buy_unconfirmed_at=clock.now() - timedelta(hours=1)
        ),
        next_check_at=clock.now() + timedelta(seconds=10),
    )
    key = _key()
    status, page = await _post(integration_client, h, order, "retry", key=key)
    assert status == 200, page
    t = page["trade"]
    assert (t["attention_reason"], t["buy_unconfirmed_at"], t["buy_pending"]) == (None, None, True)
    assert (t["resolved_at"], t["resolved_by"], t["resolved_note"]) == (None, None, None)
    assert (page["can_refund"], page["can_retry"]) == (False, False)
    (row,) = await _audit(db_session, "orders.buy.retry")
    assert (row.target_id, row.payload) == (order.number, {"reason": "buy_unconfirmed"})
    assert await _post(integration_client, h, order, "retry", key=key) == (200, page)
    assert len(await _audit(db_session, "orders.buy.retry")) == 1
    row_order, _ = await load(db_session, order)
    assert row_order.next_check_at is not None
    assert row_order.next_check_at <= clock.now()

    # Waxpeer did make the buy: the next attempt finds it by project id and adopts it.
    fake = FakeTradeClient()
    fake.lookup_returns([waxpeer_trade(order.id, status=4, id=60_000_009)])
    fake.buy_raises(AssertionError("a retried order must never be bought blind"))
    await reconcile_once(db_session, fake)
    _, trade = await load(db_session, order)
    assert fake.buy_calls == 0
    assert (trade.waxpeer_id, trade.buy_pending, trade.attention_reason) == (
        60_000_009,
        False,
        None,
    )


async def test_retry_with_nothing_at_waxpeer_buys_once(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    h = await admin_headers()
    order = await _order(db_session, trade=_attention("waxpeer_forbidden", resolved=True))
    status, _ = await _post(integration_client, h, order, "retry")
    assert status == 200
    fake = FakeTradeClient()
    await reconcile_once(db_session, fake)
    await reconcile_once(db_session, fake)
    assert fake.buy_calls == 1
    _, trade = await load(db_session, order)
    assert (trade.buy_pending, trade.status) == (False, 0)


@pytest.mark.parametrize(
    ("order_status", "trade", "over"),
    [
        ("failed", _attention("buy_unconfirmed", resolved=True), {"refunded_at": clock.now()}),
        ("buying", _attention("buy_unconfirmed", resolved=False), {}),
        ("buying", _attention("rolled_back", resolved=True), {}),
        ("buying", {"status": 0}, {}),
        ("trade_sent", _attention("ambiguous_trade", resolved=True), {}),
        ("paid", None, {}),
    ],
)
async def test_retry_refusals_write_nothing(
    *,
    integration_client: AsyncClient,
    admin_headers: Headers,
    db_session: AsyncSession,
    order_status: str,
    trade: dict[str, Any] | None,
    over: dict[str, Any],
) -> None:
    h = await admin_headers()
    order = await _order(db_session, status=order_status, trade=trade, **over)
    status, body = await _post(integration_client, h, order, "retry")
    assert (status, body["code"]) == (409, "not_retryable")
    assert await _audit(db_session, "orders.buy.retry") == []


# --- the buy lease ----------------------------------------------------------------------


async def test_a_running_attempt_blocks_refund_and_retry_until_released(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    h = await admin_headers()
    order = await _order(
        db_session, trade=_attention("waxpeer_forbidden", resolved=True, buy_pending=True)
    )
    lease = await take_lease(db_session, order.id)
    assert lease is not None
    page = (await integration_client.get(f"{BASE}/{order.number}", headers=h)).json()
    assert (page["can_refund"], page["can_retry"]) == (False, False)
    for action in ("refund", "retry"):
        status, body = await _post(integration_client, h, order, action)
        assert (status, body["code"]) == (409, "order_busy"), action

    await release(db_session, order.id, lease)
    status, page = await _post(integration_client, h, order, "refund")
    assert status == 200, page
    assert page["trade"]["buy_pending"] is False
    # No attempt can start after the refund: nothing is bought.
    fake = FakeTradeClient()
    outcome = await attempt_buy(db_session, fake, order_id=order.id, settings=sweep_settings())
    assert (outcome, fake.lookup_calls, fake.buy_calls) == ("nothing_to_do", 0, 0)


async def test_a_lease_waits_for_the_refund_and_then_finds_nothing_to_buy(
    db_session: AsyncSession,
) -> None:
    order = await _order(
        db_session, trade=_attention("waxpeer_forbidden", resolved=True, buy_pending=True)
    )
    admin = str(uuid.uuid4())
    factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)
    async with factory() as refunding, factory() as attempt:
        await admin_refund(refunding, number=order.number, admin_id=admin)  # holds the locks
        racing = asyncio.create_task(take_lease(attempt, order.id))
        await asyncio.sleep(0.3)
        assert not racing.done()  # the lease waits on the order row
        await refunding.commit()
        assert await racing is None
    row, trade = await load(db_session, order)
    assert (row.status, trade.buy_pending) == ("failed", False)


# --- can_refund / can_retry are the actions' own rule ------------------------------------

_STATES: list[tuple[str, str, dict[str, Any] | None, dict[str, Any]]] = [
    ("unresolved", "buying", _attention("buy_unconfirmed", resolved=False), {}),
    ("unconfirmed", "buying", _attention("buy_unconfirmed", resolved=True), {}),
    ("ambiguous", "buying", _attention("ambiguous_trade", resolved=True), {}),
    ("forbidden", "buying", _attention("waxpeer_forbidden", resolved=True, buy_pending=True), {}),
    (
        "leased",
        "buying",
        _attention("waxpeer_forbidden", resolved=True, buy_pending=True),
        {"leased": True},
    ),
    ("rolled_back", "buying", _attention("rolled_back", resolved=True), {}),
    ("divergence", "delivered", _attention("audit_divergence", resolved=True), {}),
    ("sent", "trade_sent", {"status": 4}, {}),
    ("delivered", "delivered", {"status": 5}, {}),
    (
        "refunded",
        "failed",
        _attention("buy_unconfirmed", resolved=True),
        {"refunded_at": clock.now(), "refunded_to": "balance"},
    ),
    ("no_trade", "buying", None, {}),
    ("pending", "pending", None, {}),
]


@pytest.mark.parametrize(("label", "status", "trade", "over"), _STATES, ids=[s[0] for s in _STATES])
@pytest.mark.parametrize("action", ["refund", "retry"])
async def test_the_flags_say_what_the_action_does(
    *,
    integration_client: AsyncClient,
    admin_headers: Headers,
    db_session: AsyncSession,
    label: str,
    status: str,
    trade: dict[str, Any] | None,
    over: dict[str, Any],
    action: str,
) -> None:
    h = await admin_headers()
    over = dict(over)  # the parametrize dict is shared by both actions
    if over.pop("leased", False):
        over["next_check_at"] = clock.now() + timedelta(minutes=4)
    order = await _order(db_session, status=status, trade=trade, **over)
    page = (await integration_client.get(f"{BASE}/{order.number}", headers=h)).json()
    allowed = page["can_refund"] if action == "refund" else page["can_retry"]
    row, row_trade = await _fresh(db_session, order)
    assert allowed == (can_refund if action == "refund" else can_retry)(row, row_trade)
    code, _ = await _post(integration_client, h, order, action)
    assert code == (200 if allowed else 409), label


async def _fresh(db: AsyncSession, order: Order) -> tuple[Order, SkinTrade | None]:
    row = await db.scalar(
        select(Order).where(Order.id == order.id).execution_options(populate_existing=True)
    )
    assert row is not None
    trade = await db.scalar(
        select(SkinTrade)
        .where(SkinTrade.order_id == order.id)
        .execution_options(populate_existing=True)
    )
    await db.commit()
    return row, trade
