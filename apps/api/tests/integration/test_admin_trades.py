"""Admin «Обмены»: one table over every order, whatever its source (Waxpeer, Skinslink,
LIS-SKINS) and channel — tabs with counts, search, the row's shape and the query budget."""

from __future__ import annotations

import secrets
from collections.abc import Awaitable, Callable
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from csmarket.core import clock
from csmarket.modules.orders.models import Order
from csmarket.modules.public_api.models import ApiKey
from csmarket.modules.users.models import User
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.integration.lisskins_factory import OFFER as LS_OFFER
from tests.integration.lisskins_factory import make_lisskins_order
from tests.integration.orders_factory import build_order, make_item_and_rate, make_trade
from tests.integration.payments_factory import make_user
from tests.integration.skinslink_factory import OFFER as SL_OFFER
from tests.integration.skinslink_factory import make_skinslink_order

Headers = Callable[[], Awaitable[dict[str, str]]]
URL = "/api/v1/admin/trades"
#: A redrawn fake trade link — never a real partner/token.
LINK = "https://steamcommunity.com/tradeoffer/new/?partner=39734281&token=ZxCvBn9q"


async def _order(
    db: AsyncSession,
    *,
    user: User | None = None,
    minutes_ago: float = 0,
    trade: dict[str, object] | None = None,
    **overrides: object,
) -> Order:
    """A committed kassa-paid Waxpeer order (``buying`` unless overridden), its trade if given."""
    owner = user or await make_user(db)
    item, fx = await make_item_and_rate(db)
    values: dict[str, object] = {
        "status": "buying",
        "paid_with": "payme",
        "paid_at": clock.now(),
        "trade_link": LINK,
        "created_at": clock.now() - timedelta(minutes=minutes_ago),
    }
    values.update(overrides)
    order = await build_order(db, user=owner, item=item, fx=fx, **values)
    await db.commit()
    if trade is not None:
        await make_trade(db, order, **trade)
    return order


async def _page(
    client: AsyncClient, h: dict[str, str], **params: str
) -> dict[str, Any]:  # Any: the JSON body
    r = await client.get(URL, params=params, headers=h)
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    return body


def _numbers(body: dict[str, Any]) -> list[str]:  # Any: the JSON body
    return [row["number"] for row in body["items"]]


async def _mixed(db: AsyncSession) -> dict[str, Order]:
    """One order per row state across the three sources, oldest first."""
    later = clock.now() + timedelta(days=6)
    out: dict[str, Order] = {}
    out["pending"] = await _order(db, minutes_ago=20, status="pending", paid_with=None)
    out["wx_buying"] = await _order(db, minutes_ago=19, trade={"status": 0})
    out["wx_sent"] = await _order(
        db, minutes_ago=18, status="trade_sent", trade={"status": 4, "trade_id": "7700112233"}
    )
    out["wx_hold"] = await _order(
        db,
        minutes_ago=17,
        status="delivered",
        trade={"status": 4, "trade_id": "7700112244", "release_date": later},
    )
    out["wx_delivered"] = await _order(
        db, minutes_ago=16, status="delivered", trade={"status": 5, "is_released": True}
    )
    out["wx_refunded"] = await _order(
        db,
        minutes_ago=15,
        status="returned",
        refunded_at=clock.now(),
        refunded_to="balance",
        failure_reason="not_accepted",
        trade={"status": 6},
    )
    out["cancelled"] = await _order(db, minutes_ago=14, status="cancelled", paid_with=None)
    sl_hold, _ = await make_skinslink_order(
        db, purchase_status="hold", hold_end_date=later, offer_id="6900000001"
    )
    out["sl_hold"] = await _age(db, sl_hold, 13)
    sl_flagged, _ = await make_skinslink_order(
        db, attention_reason="rolled_back", purchase_id=180, offer_id="6900000002"
    )
    out["sl_flagged"] = await _age(db, sl_flagged, 12)
    ls_sent, _ = await make_lisskins_order(db)
    out["ls_sent"] = await _age(db, ls_sent, 11)
    ls_held, _ = await make_lisskins_order(
        db, status="failed", skin_status="return", purchase_id=56
    )
    out["ls_failed_held"] = await _age(db, ls_held, 10)
    return out


async def _age(db: AsyncSession, order: Order, minutes: float) -> Order:
    order.created_at = clock.now() - timedelta(minutes=minutes)
    await db.commit()
    return order


async def test_every_source_shows_newest_first_with_one_state_vocabulary(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    h = await admin_headers()
    made = await _mixed(db_session)
    body = await _page(integration_client, h)
    assert _numbers(body) == [o.number for o in reversed(made.values())]
    state = {row["number"]: row["trade_state"] for row in body["items"]}
    assert {name: state[o.number] for name, o in made.items()} == {
        "pending": "pending",
        "wx_buying": "buying",
        "wx_sent": "sent",
        "wx_hold": "hold",
        "wx_delivered": "delivered",
        "wx_refunded": "refunded",
        "cancelled": "cancelled",
        "sl_hold": "hold",
        "sl_flagged": "sent",
        "ls_sent": "sent",
        "ls_failed_held": "failed_held",
    }
    by_number = {row["number"]: row for row in body["items"]}
    assert by_number[made["wx_hold"].number]["protected_until"] is not None
    assert by_number[made["sl_hold"].number]["protected_until"] is not None
    assert by_number[made["wx_sent"].number]["protected_until"] is None
    assert by_number[made["wx_refunded"].number]["failure_reason"] == "not_accepted"
    assert by_number[made["sl_flagged"].number]["attention_reason"] == "rolled_back"
    assert by_number[made["sl_flagged"].number]["source_status"] == "active"
    assert by_number[made["wx_sent"].number]["source_status"] == "4"
    assert by_number[made["pending"].number]["source_status"] is None


async def test_tabs_filter_and_count_across_sources(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    h = await admin_headers()
    made = await _mixed(db_session)
    # A Waxpeer attention, resolved: not counted.
    resolved = await _order(
        db_session, trade={"attention_reason": "ambiguous_trade", "resolved_at": clock.now()}
    )
    wx_flag = await _order(db_session, trade={"attention_reason": "buy_unconfirmed"})
    ls_flag, _ = await make_lisskins_order(db_session, attention_reason="audit_divergence")

    def names(*keys: str) -> set[str]:
        return {made[k].number for k in keys}

    everything = await _page(integration_client, h)
    assert everything["counts"] == {
        "all": 14,
        "active": 7,
        "hold": 2,
        "attention": 3,
        "refunds": 1,
    }
    active = set(_numbers(await _page(integration_client, h, view="active")))
    assert active == names("wx_buying", "wx_sent", "sl_flagged", "ls_sent") | {
        resolved.number,
        wx_flag.number,
        ls_flag.number,
    }
    hold = await _page(integration_client, h, view="hold")
    assert set(_numbers(hold)) == names("wx_hold", "sl_hold")
    attention = await _page(integration_client, h, view="attention")
    assert set(_numbers(attention)) == {made["sl_flagged"].number, wx_flag.number, ls_flag.number}
    refunds = await _page(integration_client, h, view="refunds")
    assert _numbers(refunds) == [made["wx_refunded"].number]
    # ``q`` narrows the items, never the counts.
    one = await _page(integration_client, h, view="hold", q=made["sl_hold"].number)
    assert _numbers(one) == [made["sl_hold"].number]
    assert one["counts"] == everything["counts"]


async def test_active_holds_paid_buying_and_unaccepted_sent_only(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    h = await admin_headers()
    paid = await _order(db_session, status="paid")
    buying = await _order(db_session, trade={"status": 2})
    sent = await _order(db_session, status="trade_sent", trade={"status": 4, "trade_id": "77"})
    await _order(db_session, status="delivered", trade={"status": 5})
    await make_skinslink_order(db_session, purchase_status="hold")
    body = await _page(integration_client, h, view="active")
    assert set(_numbers(body)) == {paid.number, buying.number, sent.number}
    assert body["counts"]["active"] == 3


async def test_search_by_steam_offer_id_of_any_source(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    h = await admin_headers()
    wx = await _order(
        db_session, status="trade_sent", trade={"status": 4, "trade_id": "7700112233"}
    )
    sl, _ = await make_skinslink_order(db_session)
    ls, _ = await make_lisskins_order(db_session)
    assert _numbers(await _page(integration_client, h, q="7700112233")) == [wx.number]
    assert _numbers(await _page(integration_client, h, q=SL_OFFER)) == [sl.number]
    assert _numbers(await _page(integration_client, h, q=LS_OFFER)) == [ls.number]
    # Exact only: a part of an offer id finds nothing.
    assert _numbers(await _page(integration_client, h, q="77001122")) == []
    # A number prefix and a name still work.
    assert _numbers(await _page(integration_client, h, q=sl.number.lower())) == [sl.number]


async def test_row_shape_money_item_buyer_offer_and_masked_link(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    h = await admin_headers()
    buyer = await make_user(db_session)
    buyer.display_name = "Dana"
    buyer.avatar_url = "https://avatars.example/dana.jpg"
    await db_session.commit()
    order = await _order(
        db_session,
        user=buyer,
        status="trade_sent",
        phase="Phase 2",
        float_value=Decimal("0.123400"),
        cost_usd=Decimal("12.345"),
        price_usd=Decimal("13.58"),
        trade={"status": 4, "trade_id": "7700112233", "bought_units": 12_000},
    )
    body = await _page(integration_client, h)
    row = body["items"][0]
    assert "ZxCvBn9q" not in str(body)
    assert row["number"] == order.number
    assert (row["status"], row["source"], row["channel"], row["api_owner"]) == (
        "trade_sent",
        "waxpeer",
        "site",
        None,
    )
    item = row["item"]
    assert item["name"] == order.market_hash_name
    assert (item["phase"], item["float_value"]) == ("Phase 2", "0.1234")
    assert set(item) == {"name", "phase", "image_url", "rarity_color", "float_value"}
    assert (row["price_uzs"], row["price_usd"]) == ("171800", "13.580000")
    # Against what Waxpeer charged (12 000 units = $12), not the checkout cost.
    assert (row["cost_usd"], row["margin_usd"], row["margin_pct"]) == (
        "12.000000",
        "1.580000",
        "11.6",
    )
    assert row["paid_with"] == "payme"
    assert row["buyer"] == {
        "id": buyer.id,
        "display_name": "Dana",
        "avatar_url": "https://avatars.example/dana.jpg",
    }
    assert (row["steam_offer_id"], row["offer_url"]) == (
        "7700112233",
        "https://steamcommunity.com/tradeoffer/7700112233/",
    )
    assert row["trade_link_masked"] == (
        "https://steamcommunity.com/tradeoffer/new/?partner=39734281&token=••••9q"
    )


async def test_an_api_order_names_the_key_owner(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    h = await admin_headers()
    partner = await make_user(db_session)
    partner.display_name = "Partner Co"
    key = ApiKey(user_id=partner.id, token_hash=secrets.token_hex(32))
    db_session.add(key)
    await db_session.commit()
    order = await _order(
        db_session,
        user=partner,
        channel="api",
        api_key_id=key.id,
        client_order_id="c-1",
        pricing_profile="retail",
        paid_with="usd_wallet",
    )
    sl, _ = await make_skinslink_order(db_session, amount_units=12_000)
    by_number = {r["number"]: r for r in (await _page(integration_client, h))["items"]}
    row = by_number[order.number]
    assert (row["channel"], row["api_owner"], row["paid_with"]) == (
        "api",
        "Partner Co",
        "usd_wallet",
    )
    # Skinslink: its offer id and what it charged.
    s = by_number[sl.number]
    assert (s["source"], s["steam_offer_id"], s["cost_usd"]) == ("skinslink", SL_OFFER, "12.000000")


@pytest.mark.parametrize("view", ["mine", "orders"])
async def test_trades_refuses_an_unknown_view(
    integration_client: AsyncClient, admin_headers: Headers, view: str
) -> None:
    r = await integration_client.get(URL, params={"view": view}, headers=await admin_headers())
    assert r.status_code == 422


async def _statements(client: AsyncClient, engine: AsyncEngine, h: dict[str, str]) -> int:
    statements: list[str] = []

    def _capture(*args: object) -> None:
        statements.append(str(args[2]))

    sync = engine.sync_engine
    event.listen(sync, "before_cursor_execute", _capture)
    try:
        r = await client.get(URL, params={"limit": 100}, headers=h)
    finally:
        event.remove(sync, "before_cursor_execute", _capture)
    assert r.status_code == 200, r.text
    return len(statements)


async def test_query_count_is_constant_whatever_the_sources(
    integration_client: AsyncClient,
    admin_headers: Headers,
    db_session: AsyncSession,
    db_engine: AsyncEngine,
) -> None:
    h = await admin_headers()
    await _order(db_session, trade={"attention_reason": "rolled_back"})
    few = await _statements(integration_client, db_engine, h)
    await _mixed(db_session)
    for i in range(4):
        await make_skinslink_order(db_session, purchase_status="hold", purchase_id=200 + i)
        await make_lisskins_order(db_session)
    assert few == await _statements(integration_client, db_engine, h)


async def test_the_dashboard_in_flight_is_the_active_tab_count(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    """One rule for «В пути»: the dashboard tile and the ``active`` tab count the same set."""
    h = await admin_headers()
    await _mixed(db_session)
    await _order(db_session, status="paid")
    tab = (await _page(integration_client, h, view="active"))["counts"]["active"]
    assert tab > 0
    r = await integration_client.get("/api/v1/admin/dashboard?days=1", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["in_flight"] == tab
