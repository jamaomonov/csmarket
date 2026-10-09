"""Admin API keys: list with sales, card, tariff switch, revoke (plan C, Task 4)."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from csmarket.core import config as cfg
from csmarket.modules.admin.models import AdminAuditLog
from csmarket.modules.orders.models import Order
from csmarket.modules.public_api import keys
from csmarket.modules.public_api.models import ApiKey, ApiWebhook, ApiWebhookDelivery
from csmarket.modules.skins.models import SkinItem
from csmarket.modules.skinslink.models import SkinslinkItem, SkinslinkState
from csmarket.modules.users.models import User
from csmarket.modules.wallet.api import admin_adjust_usd
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.orders_factory import FAKE_TRADE_LINK, build_order, make_item_and_rate
from tests.integration.payments_factory import make_user

Headers = Callable[[], Awaitable[dict[str, str]]]
BASE = "/api/v1/admin/api-keys"
ORDERS = "/api/v1/public/orders"
ADMIN_ID = "00000000-0000-4000-8000-000000000001"


def _idem() -> dict[str, str]:
    return {"Idempotency-Key": f"admin-keys-{uuid.uuid4()}"}


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for name, value in {
        "SKINS_BUY_ENABLED": "true",
        "SKINSLINK_ENABLED": "true",
        "SKINSLINK_API_KEY": "k",
        "SKINSLINK_SECRET": "s",
    }.items():
        monkeypatch.setenv(f"CSMARKET_{name}", value)
    cfg.get_settings.cache_clear()
    yield
    cfg.get_settings.cache_clear()


async def _partner(
    db: AsyncSession, name: str, profile: str = "retail"
) -> tuple[User, ApiKey, str]:
    user = await make_user(db)
    user.display_name = name
    user.usd_wallet_enabled = True
    key, token = await keys.issue(db, user=user)
    key.pricing_profile = profile
    await db.commit()
    return user, key, token


async def _api_order(
    db: AsyncSession, user: User, key: ApiKey, price: str, cost: str, **extra: object
) -> Order:
    item, fx = await make_item_and_rate(db)
    order = await build_order(
        db,
        user=user,
        item=item,
        fx=fx,
        channel="api",
        api_key_id=key.id,
        client_order_id=f"c-{uuid.uuid4()}",
        pricing_profile=key.pricing_profile,
        price_usd=Decimal(price),
        cost_usd=Decimal(cost),
        **extra,
    )
    await db.commit()
    return order


async def _audit(db: AsyncSession, action: str) -> list[AdminAuditLog]:
    return list(await db.scalars(select(AdminAuditLog).where(AdminAuditLog.action == action)))


# --- the gate ---------------------------------------------------------------------------

_ROUTES: list[tuple[str, str, dict[str, object] | None]] = [
    ("GET", "", None),
    ("GET", "/{id}", None),
    ("PUT", "/{id}/tariff", {"pricing_profile": "cost", "reason": "volume deal"}),
    (
        "PUT",
        "/{id}/limits",
        {
            "read_per_min": 5,
            "orders_per_min": None,
            "feed_per_min": None,
            "check_per_min": None,
            "reason": "bigger quota",
        },
    ),
    ("POST", "/{id}/revoke", {"reason": "abuse found"}),
]


@pytest.mark.parametrize("route", _ROUTES, ids=[f"{m} {p}" for m, p, _ in _ROUTES])
async def test_a_customer_is_403_on_every_route(
    integration_client: AsyncClient,
    customer_headers: Headers,
    db_session: AsyncSession,
    route: tuple[str, str, dict[str, object] | None],
) -> None:
    _, key, _ = await _partner(db_session, "Partner")
    method, path, body = route
    r = await integration_client.request(
        method,
        BASE + path.format(id=key.id),
        json=body,
        headers={**await customer_headers(), **_idem()},
    )
    assert r.status_code == 403


async def test_anonymous_is_401(integration_client: AsyncClient) -> None:
    assert (await integration_client.get(BASE)).status_code == 401


# --- list and card ----------------------------------------------------------------------


async def test_list_shows_orders_and_sums(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    user, key, token = await _partner(db_session, "Acme Reseller")
    await _api_order(db_session, user, key, "10.500", "9.250")
    await _api_order(db_session, user, key, "20.000", "18.000")
    await _api_order(
        db_session, user, key, "5.000", "4.000", refunded_at=datetime.now(UTC), status="failed"
    )
    r = await integration_client.get(BASE, headers=await admin_headers())
    assert r.status_code == 200, r.text
    [row] = r.json()["items"]
    assert row["id"] == key.id
    assert row["user"] == {"id": user.id, "display_name": "Acme Reseller"}
    assert row["pricing_profile"] == "retail"
    assert row["orders"] == 3
    assert row["revenue_usd"] == "30.500"
    assert row["cost_usd"] == "27.250"  # the refunded order's cost is not counted
    assert row["revoked_at"] is None
    assert token not in r.text
    assert "token" not in r.text


async def test_list_a_key_without_orders_is_zero(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    await _partner(db_session, "Quiet")
    [row] = (await integration_client.get(BASE, headers=await admin_headers())).json()["items"]
    assert (row["orders"], row["revenue_usd"], row["cost_usd"]) == (0, "0.000", "0.000")


async def test_list_live_first_then_revoked_with_cursor_and_search(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    a, ka, _ = await _partner(db_session, "Alpha")
    b, kb, _ = await _partner(db_session, "Beta")
    c, kc, _ = await _partner(db_session, "Gamma")
    base = datetime.now(UTC)
    ka.created_at, kb.created_at, kc.created_at = (
        base - timedelta(hours=3),
        base - timedelta(hours=2),
        base - timedelta(hours=1),
    )
    kc.revoked_at = base  # the newest, but revoked: goes last
    await db_session.commit()
    h = await admin_headers()
    seen: list[str] = []
    cursor: str | None = None
    for _ in range(3):
        params: dict[str, str] = {"limit": "1"}
        if cursor:
            params["cursor"] = cursor
        page = (await integration_client.get(BASE, params=params, headers=h)).json()
        seen += [i["id"] for i in page["items"]]
        cursor = page["next_cursor"]
    assert cursor is None
    assert seen == [kb.id, ka.id, kc.id]
    found = (await integration_client.get(BASE, params={"q": "alph"}, headers=h)).json()
    assert [i["id"] for i in found["items"]] == [ka.id]
    bad = await integration_client.get(BASE, params={"cursor": "zzz"}, headers=h)
    assert bad.status_code == 422


async def test_card_has_orders_and_webhook_host_only(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    user, key, _ = await _partner(db_session, "Hooked")
    order = await _api_order(db_session, user, key, "10.000", "9.000")
    db_session.add(
        ApiWebhook(user_id=user.id, url="https://hooks.partner.example/p/SECRETPATH?x=1")
    )
    db_session.add(
        ApiWebhookDelivery(
            user_id=user.id,
            order_id=order.id,
            event="order.paid",
            payload={},
            status="failed",
            attempts=3,
            last_status_code=500,
        )
    )
    await db_session.commit()
    r = await integration_client.get(f"{BASE}/{key.id}", headers=await admin_headers())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["key"]["orders"] == 1
    assert body["key"]["cost_usd"] == "9.000"
    assert [o["number"] for o in body["orders"]] == [order.number]
    assert body["webhook"]["host"] == "hooks.partner.example"
    assert body["webhook"]["last_delivery"]["status"] == "failed"
    assert body["webhook"]["last_delivery"]["last_status_code"] == 500
    assert "SECRETPATH" not in r.text


async def test_card_without_webhook_and_unknown_id(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    _, key, _ = await _partner(db_session, "NoHook")
    h = await admin_headers()
    assert (await integration_client.get(f"{BASE}/{key.id}", headers=h)).json()["webhook"] is None
    assert (await integration_client.get(f"{BASE}/{uuid.uuid4()}", headers=h)).status_code == 404
    assert (await integration_client.get(f"{BASE}/nope", headers=h)).status_code == 404


# --- tariff -----------------------------------------------------------------------------


async def _item(db: AsyncSession) -> SkinItem:
    item, _ = await make_item_and_rate(db)
    item.active = True
    db.add(
        SkinslinkItem(
            id=str(38_000_000_000 + int(uuid.uuid4().int % 1_000_000_000)),
            market_hash_name=item.market_hash_name,
            phase="",
            price_units=9000,
            skin_item_id=item.id,
        )
    )
    if await db.get(SkinslinkState, 1) is None:
        db.add(SkinslinkState(id=1, cursor="c", mirror_synced_at=datetime.now(UTC)))
    await db.commit()
    await db.refresh(item)
    return item


def _buy(item: SkinItem, cid: str) -> dict[str, object]:
    return {
        "item_id": item.id,
        "max_price_usd": "100",
        "trade_link": FAKE_TRADE_LINK,
        "client_order_id": cid,
    }


async def test_tariff_change_is_audited_and_only_the_next_order_uses_it(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    item = await _item(db_session)
    user, key, token = await _partner(db_session, "Switcher")
    key_id = key.id
    await admin_adjust_usd(
        db_session,
        user_id=user.id,
        amount=Decimal(100_000),
        reason="seed",
        admin_id=ADMIN_ID,
        idempotency_key=f"seed-{uuid.uuid4()}",
    )
    await db_session.commit()
    auth = {"Authorization": f"Bearer {token}"}
    first = await integration_client.post(ORDERS, json=_buy(item, "a-1"), headers=auth)
    assert first.status_code == 201, first.text
    retail_price = first.json()["price_usd"]
    assert Decimal(retail_price) > Decimal("9.000")

    h = await admin_headers()
    r = await integration_client.put(
        f"{BASE}/{key.id}/tariff",
        json={"pricing_profile": "cost", "reason": "volume deal"},
        headers={**h, **_idem()},
    )
    assert r.status_code == 200, r.text
    assert r.json()["key"]["pricing_profile"] == "cost"

    second = await integration_client.post(ORDERS, json=_buy(item, "a-2"), headers=auth)
    assert second.status_code == 201, second.text
    assert second.json()["price_usd"] == "9.000"

    # The first order keeps the price and tariff stamped on it.
    db_session.expire_all()
    o1 = await db_session.scalar(select(Order).where(Order.client_order_id == "a-1"))
    o2 = await db_session.scalar(select(Order).where(Order.client_order_id == "a-2"))
    assert o1 is not None
    assert o2 is not None
    assert (o1.pricing_profile, f"{o1.price_usd:.3f}") == ("retail", retail_price)
    assert (o2.pricing_profile, f"{o2.price_usd:.3f}") == ("cost", "9.000")
    again = await integration_client.get(f"{ORDERS}/{o1.number}", headers=auth)
    assert again.json()["price_usd"] == retail_price

    [row] = await _audit(db_session, "api_keys.tariff")
    assert row.target_id == key_id
    assert row.payload == {"from": "retail", "to": "cost", "reason": "volume deal"}


async def test_tariff_replay_and_mismatch(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    _, key, _ = await _partner(db_session, "Replay")
    h = {**await admin_headers(), **_idem()}
    body = {"pricing_profile": "cost", "reason": "deal one"}
    r1 = await integration_client.put(f"{BASE}/{key.id}/tariff", json=body, headers=h)
    r2 = await integration_client.put(f"{BASE}/{key.id}/tariff", json=body, headers=h)
    assert r1.status_code == r2.status_code == 200
    assert r2.json() == r1.json()
    assert len(await _audit(db_session, "api_keys.tariff")) == 1
    other = await integration_client.put(
        f"{BASE}/{key.id}/tariff", json={**body, "reason": "another"}, headers=h
    )
    assert other.status_code == 409
    assert other.json()["code"] == "idempotency_mismatch"


async def test_tariff_needs_a_key_and_a_valid_body(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    _, key, _ = await _partner(db_session, "Strict")
    h = await admin_headers()
    url = f"{BASE}/{key.id}/tariff"
    ok = {"pricing_profile": "cost", "reason": "deal one"}
    assert (await integration_client.put(url, json=ok, headers=h)).status_code in (400, 422)
    for bad in ({"pricing_profile": "free", "reason": "deal one"}, {"pricing_profile": "cost"}):
        r = await integration_client.put(url, json=bad, headers={**h, **_idem()})
        assert r.status_code == 422


async def test_tariff_on_a_revoked_key_is_409(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    _, key, _ = await _partner(db_session, "Dead")
    key.revoked_at = datetime.now(UTC)
    await db_session.commit()
    r = await integration_client.put(
        f"{BASE}/{key.id}/tariff",
        json={"pricing_profile": "cost", "reason": "deal one"},
        headers={**await admin_headers(), **_idem()},
    )
    assert r.status_code == 409
    assert r.json()["code"] == "api_key_revoked"
    assert await _audit(db_session, "api_keys.tariff") == []


# --- revoke -----------------------------------------------------------------------------


async def test_revoke_kills_the_key_and_is_audited(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    _, key, token = await _partner(db_session, "Doomed")
    auth = {"Authorization": f"Bearer {token}"}
    assert (await integration_client.get(ORDERS, headers=auth)).status_code != 401
    h = await admin_headers()
    r = await integration_client.post(
        f"{BASE}/{key.id}/revoke", json={"reason": "abuse found"}, headers={**h, **_idem()}
    )
    assert r.status_code == 200, r.text
    assert r.json()["key"]["revoked_at"] is not None
    assert (await integration_client.get(ORDERS, headers=auth)).status_code == 401
    [row] = await _audit(db_session, "api_keys.revoke")
    assert row.target_id == key.id
    assert row.payload == {"reason": "abuse found"}
    again = await integration_client.post(
        f"{BASE}/{key.id}/revoke", json={"reason": "abuse found"}, headers={**h, **_idem()}
    )
    assert again.status_code == 409
    assert again.json()["code"] == "api_key_revoked"


async def test_set_pricing_profile_unit(db_session: AsyncSession) -> None:
    _, key, _ = await _partner(db_session, "Unit")
    await keys.set_pricing_profile(db_session, key=key, profile="cost")
    assert key.pricing_profile == "cost"
    # A reissue carries the new tariff over.
    user = await db_session.get(User, key.user_id)
    assert user is not None
    new_key, _ = await keys.issue(db_session, user=user)
    assert new_key.pricing_profile == "cost"


async def test_same_tariff_is_409_and_not_audited(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    _, key, _ = await _partner(db_session, "Same")
    r = await integration_client.put(
        f"{BASE}/{key.id}/tariff",
        json={"pricing_profile": "retail", "reason": "no change"},
        headers={**await admin_headers(), **_idem()},
    )
    assert r.status_code == 409
    assert r.json()["code"] == "tariff_unchanged"
    assert await _audit(db_session, "api_keys.tariff") == []


# --- limits and allow-list --------------------------------------------------------------

_NO_LIMITS: dict[str, int | None] = {
    "read_per_min": None,
    "orders_per_min": None,
    "feed_per_min": None,
    "check_per_min": None,
}


async def test_set_limits_audits_and_shows_effective(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    _, key, _ = await _partner(db_session, "Limits")
    key_id = key.id
    body = {**_NO_LIMITS, "read_per_min": 600, "orders_per_min": 30, "reason": "YuPay storefront"}
    r = await integration_client.put(
        f"{BASE}/{key_id}/limits", json=body, headers={**await admin_headers(), **_idem()}
    )
    assert r.status_code == 200, r.text
    row = r.json()["key"]
    assert row["limits"] == {
        "read_per_min": 600,
        "orders_per_min": 30,
        "feed_per_min": 1,
        "check_per_min": 30,
    }
    assert row["custom_limits"] == ["read_per_min", "orders_per_min"]
    [audit] = await _audit(db_session, "api_keys.limits")
    assert audit.target_id == key_id
    assert audit.payload == {
        "from": _NO_LIMITS,
        "to": {**_NO_LIMITS, "read_per_min": 600, "orders_per_min": 30},
        "reason": "YuPay storefront",
    }


async def test_limits_replay_same_key(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    _, key, _ = await _partner(db_session, "LimitsReplay")
    h = {**await admin_headers(), **_idem()}
    body = {**_NO_LIMITS, "feed_per_min": 4, "reason": "more feed"}
    r1 = await integration_client.put(f"{BASE}/{key.id}/limits", json=body, headers=h)
    r2 = await integration_client.put(f"{BASE}/{key.id}/limits", json=body, headers=h)
    assert r1.status_code == r2.status_code == 200
    assert r2.json() == r1.json()
    assert len(await _audit(db_session, "api_keys.limits")) == 1


async def test_limits_out_of_range_is_422(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    _, key, _ = await _partner(db_session, "LimitsRange")
    h = await admin_headers()
    for bad in (0, 10_001):
        r = await integration_client.put(
            f"{BASE}/{key.id}/limits",
            json={**_NO_LIMITS, "read_per_min": bad, "reason": "out of range"},
            headers={**h, **_idem()},
        )
        assert r.status_code == 422
    assert await _audit(db_session, "api_keys.limits") == []


async def test_limits_unchanged_is_409(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    _, key, _ = await _partner(db_session, "LimitsSame")
    r = await integration_client.put(
        f"{BASE}/{key.id}/limits",
        json={**_NO_LIMITS, "reason": "no change"},
        headers={**await admin_headers(), **_idem()},
    )
    assert r.status_code == 409
    assert r.json()["code"] == "limits_unchanged"
    assert await _audit(db_session, "api_keys.limits") == []


async def test_limits_on_revoked_key_is_409(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    _, key, _ = await _partner(db_session, "LimitsDead")
    key.revoked_at = datetime.now(UTC)
    await db_session.commit()
    r = await integration_client.put(
        f"{BASE}/{key.id}/limits",
        json={**_NO_LIMITS, "read_per_min": 5, "reason": "too late"},
        headers={**await admin_headers(), **_idem()},
    )
    assert r.status_code == 409
    assert r.json()["code"] == "api_key_revoked"
    assert await _audit(db_session, "api_keys.limits") == []


async def test_card_shows_ip_allowlist(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    _, key, _ = await _partner(db_session, "Allow")
    h = await admin_headers()
    empty = await integration_client.get(f"{BASE}/{key.id}", headers=h)
    assert empty.json()["key"]["ip_allowlist"] == []
    key.ip_allowlist = ["203.0.113.0/24", "2001:db8::1/128"]
    await db_session.commit()
    full = await integration_client.get(f"{BASE}/{key.id}", headers=h)
    assert full.json()["key"]["ip_allowlist"] == ["203.0.113.0/24", "2001:db8::1/128"]
