"""Admin orders API, the reads: the gate, search, the order page (M4a Task 12). The trades
page is in ``test_admin_trades.py``, the actions in ``test_admin_orders_actions.py``."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import timedelta
from decimal import Decimal
from typing import get_args

import pytest
from csmarket.core import clock
from csmarket.core.ids import new_id
from csmarket.modules.orders.models import ATTENTION_REASONS, FAILURE_REASONS, Order
from csmarket.modules.payments.models import Payment
from csmarket.modules.users.models import User
from httpx import AsyncClient
from sqlalchemy import event, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.integration.lisskins_factory import OFFER, make_lisskins_order
from tests.integration.orders_factory import build_order, make_item_and_rate, make_trade
from tests.integration.payments_factory import make_user
from tests.integration.skinslink_factory import make_skinslink_order

Headers = Callable[[], Awaitable[dict[str, str]]]
#: A redrawn fake trade link — never a real partner/token.
LINK = "https://steamcommunity.com/tradeoffer/new/?partner=39734281&token=ZxCvBn9q"
PRICE = Decimal(171_800)


def _key() -> dict[str, str]:
    return {"Idempotency-Key": f"admin-orders-{uuid.uuid4()}"}


async def _named(db: AsyncSession, name: str) -> User:
    user = await make_user(db)
    user.display_name = name
    await db.commit()
    return user


async def _order(
    db: AsyncSession,
    *,
    user: User | None = None,
    name: str = "AK-47 | Redline (Field-Tested)",
    minutes_ago: float = 0,
    trade: dict[str, object] | None = None,
    **overrides: object,
) -> Order:
    """A committed kassa-paid order (``buying`` unless overridden), its trade if given."""
    owner = user or await make_user(db)
    item, fx = await make_item_and_rate(db)
    values: dict[str, object] = {
        "status": "buying",
        "paid_with": "payme",
        "paid_at": clock.now(),
        "price_uzs": PRICE,
        "trade_link": LINK,
        "market_hash_name": name,
        "created_at": clock.now() - timedelta(minutes=minutes_ago),
    }
    values.update(overrides)
    order = await build_order(db, user=owner, item=item, fx=fx, **values)
    await db.commit()
    if trade is not None:
        await make_trade(db, order, **trade)
    return order


# --- the gate ---------------------------------------------------------------------------

_ROUTES: list[tuple[str, str, dict[str, object] | None]] = [
    ("GET", "/orders", None),
    ("GET", "/orders/{n}", None),
    ("GET", "/trades", None),
    ("POST", "/orders/{n}/resolve", {"note": "checked"}),
    ("POST", "/orders/{n}/refund", None),
    ("POST", "/orders/{n}/retry", None),
]


@pytest.mark.parametrize("route", _ROUTES, ids=[f"{m} {p}" for m, p, _ in _ROUTES])
async def test_a_customer_is_403_and_anonymous_401_on_every_route(
    integration_client: AsyncClient,
    customer_headers: Headers,
    db_session: AsyncSession,
    route: tuple[str, str, dict[str, object] | None],
) -> None:
    method, path, body = route
    h = await customer_headers()
    order = await _order(db_session, trade={"attention_reason": "buy_unconfirmed"})
    url = "/api/v1/admin" + path.format(n=order.number)
    r = await integration_client.request(method, url, json=body, headers={**h, **_key()})
    assert r.status_code == 403, r.text
    assert (await integration_client.request(method, url, json=body)).status_code == 401


@pytest.mark.parametrize("number", ["ZZZZZZZZ", "bad", "T1234567"])
@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "", None),
        ("POST", "/resolve", {"note": None}),
        ("POST", "/refund", None),
        ("POST", "/retry", None),
    ],
)
async def test_an_unknown_order_is_404(
    *,
    integration_client: AsyncClient,
    admin_headers: Headers,
    number: str,
    method: str,
    path: str,
    body: dict[str, object] | None,
) -> None:
    h = {**(await admin_headers()), **_key()}
    r = await integration_client.request(
        method, f"/api/v1/admin/orders/{number}{path}", json=body, headers=h
    )
    assert r.status_code == 404, r.text


# --- the orders list --------------------------------------------------------------------


async def test_list_row_shape_newest_first_and_masked_nothing(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    h = await admin_headers()
    buyer = await _named(db_session, "Dana")
    older = await _order(db_session, user=buyer, minutes_ago=5, phase="Phase 2")
    newer = await _order(
        db_session, user=buyer, trade={"attention_reason": "buy_unconfirmed", "seller": {}}
    )
    r = await integration_client.get("/api/v1/admin/orders", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert [o["number"] for o in body["items"]] == [newer.number, older.number]
    assert body["next_cursor"] is None
    assert body["items"][0] == {
        "number": newer.number,
        "status": "buying",
        "name": "AK-47 | Redline (Field-Tested)",
        "phase": None,
        "price_uzs": "171800",
        "paid_with": "payme",
        "user": {"id": buyer.id, "display_name": "Dana"},
        "created_at": body["items"][0]["created_at"],
        "attention_reason": "buy_unconfirmed",
        "protected_until": None,
        "protected_estimated": False,
    }
    assert body["items"][1]["phase"] == "Phase 2"
    assert body["items"][1]["attention_reason"] is None
    assert "ZxCvBn9q" not in r.text
    assert "39734281" not in r.text


async def test_search_by_number_prefix_or_by_name(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    h = await admin_headers()
    knife = await _order(db_session, name="★ Karambit | Doppler (Factory New)")
    rifle = await _order(db_session, name="AK-47 | 100%_Real (Field-Tested)")
    other = await _order(db_session, name="AWP | Asiimov (Field-Tested)")

    async def numbers(q: str) -> list[str]:
        r = await integration_client.get("/api/v1/admin/orders", params={"q": q}, headers=h)
        assert r.status_code == 200, r.text
        return [o["number"] for o in r.json()["items"]]

    # A number prefix in any case; the whole number too.
    assert knife.number in await numbers(knife.number[:3].lower())
    assert await numbers(knife.number) == [knife.number]
    # Part of the name, any case; ``%`` and ``_`` literal.
    assert await numbers("karambit | DOPP") == [knife.number]
    assert await numbers("100%_") == [rifle.number]
    assert await numbers("100%x") == []
    # Longer than a number: the name only.
    assert set(await numbers("Field-Tested")) == {rifle.number, other.number}
    assert await numbers("nothing-like-this") == []


async def test_filters_by_status_and_user(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    h = await admin_headers()
    alice = await make_user(db_session)
    a_buying = await _order(db_session, user=alice)
    a_delivered = await _order(db_session, user=alice, status="delivered")
    b_delivered = await _order(db_session, status="delivered")

    async def numbers(**params: str) -> set[str]:
        r = await integration_client.get("/api/v1/admin/orders", params=params, headers=h)
        assert r.status_code == 200, r.text
        return {o["number"] for o in r.json()["items"]}

    assert await numbers(status="delivered") == {a_delivered.number, b_delivered.number}
    assert await numbers(user_id=alice.id) == {a_buying.number, a_delivered.number}
    assert await numbers(user_id=alice.id, status="delivered") == {a_delivered.number}


@pytest.mark.parametrize(
    "params",
    [
        {"status": "lost"},
        {"user_id": "not-a-uuid"},
        {"limit": 0},
        {"limit": 101},
        {"cursor": "%%%nope"},
        {"q": "ak\x00"},
        {"q": "x" * 101},
    ],
)
async def test_list_refuses_bad_params(
    integration_client: AsyncClient, admin_headers: Headers, params: dict[str, str | int]
) -> None:
    r = await integration_client.get(
        "/api/v1/admin/orders", params=params, headers=await admin_headers()
    )
    assert r.status_code == 422, r.text


async def test_list_pages_without_gaps_or_duplicates(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    h = await admin_headers()
    for i in range(13):
        await _order(db_session, minutes_ago=i)
    seen: list[str] = []
    cursor: str | None = None
    while True:
        params: dict[str, str | int] = {"limit": 5}
        if cursor is not None:
            params["cursor"] = cursor
        page = (
            await integration_client.get("/api/v1/admin/orders", params=params, headers=h)
        ).json()
        seen += [o["number"] for o in page["items"]]
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert len(seen) == len(set(seen)) == 13


async def _statements(client: AsyncClient, engine: AsyncEngine, url: str, h: dict[str, str]) -> int:
    statements: list[str] = []

    def _capture(*args: object) -> None:
        statements.append(str(args[2]))

    sync = engine.sync_engine
    event.listen(sync, "before_cursor_execute", _capture)
    try:
        r = await client.get(url, params={"limit": 100}, headers=h)
    finally:
        event.remove(sync, "before_cursor_execute", _capture)
    assert r.status_code == 200, r.text
    return len(statements)


async def test_list_query_count_is_constant(
    integration_client: AsyncClient,
    admin_headers: Headers,
    db_session: AsyncSession,
    db_engine: AsyncEngine,
) -> None:
    url = "/api/v1/admin/orders"
    h = await admin_headers()
    for _ in range(3):
        await _order(db_session, trade={"attention_reason": "rolled_back"})
    few = await _statements(integration_client, db_engine, url, h)
    for _ in range(12):
        await _order(db_session, trade={"status": 4, "trade_id": "7700112233"})
    for i in range(3):
        await make_skinslink_order(db_session, purchase_status="hold", purchase_id=300 + i)
        await make_lisskins_order(db_session)
    assert few == await _statements(integration_client, db_engine, url, h)


# --- the order page ---------------------------------------------------------------------


async def test_detail_shows_every_column_masked_link_trade_payments_and_margin(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    h = await admin_headers()
    buyer = await _named(db_session, "Erin")
    order = await _order(
        db_session,
        user=buyer,
        status="trade_sent",
        cost_usd=Decimal("12.345"),
        price_usd=Decimal("13.58"),
        trade={
            "waxpeer_id": 60_000_001,
            "status": 4,
            "trade_id": "7700112233",
            "bought_units": 12_000,
            "seller": {"name": "redrawn_seller", "level": 9},
            "penalties": {"amount": 0},
            "attention_reason": "ambiguous_trade",
            "resolved_at": clock.now(),
            "resolved_by": "someone",
            "resolved_note": "one trade is ours",
        },
    )
    payment = Payment(
        id=new_id(),
        number=order.number,
        purpose="order",
        order_id=order.id,
        user_id=buyer.id,
        provider="payme",
        provider_ref=f"payme:{order.number}",
        amount_uzs=order.price_uzs,
        status="succeeded",
        succeeded_at=clock.now(),
    )
    db_session.add(payment)
    await db_session.commit()

    r = await integration_client.get(f"/api/v1/admin/orders/{order.number}", headers=h)
    assert r.status_code == 200, r.text
    assert "ZxCvBn9q" not in r.text
    body = r.json()
    o = body["order"]
    assert set(o) == {c.key for c in Order.__table__.columns} - {
        "trade_link",
        "idempotency_key",
        "trade_link_erased_at",
    } | {
        "trade_link_masked",
        "fx_rate",
        "margin_usd",
        "protected_until",
        "protected_estimated",
    }
    assert o["trade_link_masked"] == (
        "https://steamcommunity.com/tradeoffer/new/?partner=39734281&token=••••9q"
    )
    assert (o["number"], o["status"], o["user_id"]) == (order.number, "trade_sent", buyer.id)
    assert (o["cost_usd"], o["price_usd"], o["price_uzs"]) == ("12.345000", "13.580000", "171800")
    # Margin against what Waxpeer charged (12 000 units = $12), not the checkout cost.
    assert o["margin_usd"] == "1.580000"
    assert o["fx_rate"] == "12650.5000"
    assert body["user"] == {"id": buyer.id, "display_name": "Erin"}
    t = body["trade"]
    assert (t["project_id"], t["waxpeer_id"], t["status"]) == (order.id, 60_000_001, 4)
    assert t["offer_url"] == "https://steamcommunity.com/tradeoffer/7700112233/"
    assert t["seller"] == {"name": "redrawn_seller", "level": 9}
    assert t["penalties"] == {"amount": 0}
    assert (t["attention_reason"], t["resolved_note"]) == ("ambiguous_trade", "one trade is ours")
    assert body["payments"] == [
        {
            "id": payment.id,
            "provider": "payme",
            "status": "succeeded",
            "amount_uzs": "171800",
            "created_at": body["payments"][0]["created_at"],
        }
    ]
    assert (body["can_refund"], body["can_retry"]) == (False, False)


async def test_detail_margin_against_cost_before_the_buy_and_no_trade(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    order = await _order(
        db_session, status="paid", cost_usd=Decimal("12.345"), price_usd=Decimal("13.58")
    )
    r = await integration_client.get(
        f"/api/v1/admin/orders/{order.number}", headers=await admin_headers()
    )
    body = r.json()
    assert body["order"]["margin_usd"] == "1.235000"
    assert (body["trade"], body["payments"]) == (None, [])


async def test_detail_of_a_skinslink_order_shows_its_purchase(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    order, _ = await make_skinslink_order(db_session, amount_units=12_000)
    r = await integration_client.get(
        f"/api/v1/admin/orders/{order.number}", headers=await admin_headers()
    )
    body = r.json()
    assert (body["order"]["source"], body["order"]["listing_id"]) == ("skinslink", None)
    assert body["trade"] is None
    sl = body["skinslink"]
    assert (sl["purchase_id"], sl["status"], sl["offer_id"], sl["amount_usd"]) == (
        178,
        "active",
        "6912345678",
        "12.000000",
    )
    assert sl["merchant_tx_id"] == order.id
    # The margin is against what Skinslink charged.
    assert Decimal(body["order"]["margin_usd"]) == order.price_usd - Decimal(12)


async def test_detail_of_a_waxpeer_order_has_no_skinslink_block(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    order = await _order(db_session, status="paid")
    r = await integration_client.get(
        f"/api/v1/admin/orders/{order.number}", headers=await admin_headers()
    )
    assert (r.json()["order"]["source"], r.json()["skinslink"]) == ("waxpeer", None)


# --- vocabulary -------------------------------------------------------------------------


def test_the_wire_literals_match_the_columns() -> None:
    from csmarket.modules.admin.orders_schemas import AttentionReason, FailureReason

    assert get_args(AttentionReason) == ATTENTION_REASONS
    assert get_args(FailureReason) == FAILURE_REASONS


async def test_a_detail_after_the_order_moved_reads_fresh(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    h = await admin_headers()
    order = await _order(db_session, trade={"status": 0})
    first = (await integration_client.get(f"/api/v1/admin/orders/{order.number}", headers=h)).json()
    await db_session.execute(update(Order).where(Order.id == order.id).values(status="trade_sent"))
    await db_session.commit()
    again = (await integration_client.get(f"/api/v1/admin/orders/{order.number}", headers=h)).json()
    assert (first["order"]["status"], again["order"]["status"]) == ("buying", "trade_sent")


async def test_a_lisskins_orders_page_names_its_source_and_shows_its_purchase(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    order, _ = await make_lisskins_order(db_session, amount_units=12_340)
    r = await integration_client.get(
        f"/api/v1/admin/orders/{order.number}", headers=await admin_headers()
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["order"]["source"], body["order"]["offer_id"], body["order"]["listing_id"]) == (
        "lisskins",
        "ls:125345",
        None,
    )
    assert body["trade"] is None
    assert body["skinslink"] is None
    ls = body["lisskins"]
    assert (ls["custom_id"], ls["skin_id"], ls["purchase_id"], ls["status"]) == (
        order.id,
        125345,
        55,
        "wait_accept",
    )
    assert ls["offer_url"] == f"https://steamcommunity.com/tradeoffer/{OFFER}/"
    assert ls["amount_usd"] == "12.340000"


# --- Steam's protection on an accepted Skinslink trade ------------------------------------


async def test_a_skinslink_hold_shows_protected_until_in_list_and_detail(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    """Skinslink ``hold``: the buyer accepted, Steam protects the trade until its end; the order
    stays ``trade_sent`` until ``completed``, so the admin is told it is not stuck."""
    h = await admin_headers()
    end = clock.now() + timedelta(days=6)
    held, _ = await make_skinslink_order(db_session, purchase_status="hold", hold_end_date=end)
    sent, _ = await make_skinslink_order(db_session, purchase_status="active", purchase_id=179)
    rows = (await integration_client.get("/api/v1/admin/orders", headers=h)).json()["items"]
    by_number = {r["number"]: r for r in rows}
    assert by_number[held.number]["protected_until"] is not None
    assert by_number[sent.number]["protected_until"] is None
    detail = (await integration_client.get(f"/api/v1/admin/orders/{held.number}", headers=h)).json()
    assert detail["order"]["protected_until"] is not None


async def test_a_delivered_order_has_no_protected_until(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    order, _ = await make_skinslink_order(
        db_session,
        status="delivered",
        purchase_status="hold",
        hold_end_date=clock.now() + timedelta(days=1),
    )
    rows = (
        await integration_client.get("/api/v1/admin/orders", headers=await admin_headers())
    ).json()["items"]
    assert {r["number"]: r for r in rows}[order.number]["protected_until"] is None


async def test_order_rows_carry_an_open_attention_of_any_source(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    sl, _ = await make_skinslink_order(db_session, attention_reason="rolled_back")
    ls, _ = await make_lisskins_order(
        db_session, attention_reason="audit_divergence", resolved_at=clock.now()
    )
    rows = (
        await integration_client.get("/api/v1/admin/orders", headers=await admin_headers())
    ).json()["items"]
    by_number = {r["number"]: r for r in rows}
    assert by_number[sl.number]["attention_reason"] == "rolled_back"
    # Resolved: nothing waits for an admin.
    assert by_number[ls.number]["attention_reason"] is None


async def test_a_waxpeer_trade_in_protection_shows_protected_until(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    end = clock.now() + timedelta(days=7)
    held = await _order(db_session, status="delivered", trade={"status": 4, "release_date": end})
    done = await _order(db_session, status="delivered", trade={"status": 5, "is_released": True})
    h = await admin_headers()
    rows = (await integration_client.get("/api/v1/admin/orders", headers=h)).json()["items"]
    by_number = {r["number"]: r for r in rows}
    assert by_number[held.number]["protected_until"] is not None
    assert by_number[done.number]["protected_until"] is None
