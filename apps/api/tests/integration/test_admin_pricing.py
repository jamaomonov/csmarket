"""Admin pricing: edit the rules document, preview a price, override one item (M4b T7, R8).

A save reprices the catalogue in its transaction and publishes the document to Redis only
after commit; a failed save leaves the old prices, rules and cache everywhere. A preview
writes nothing. Every write takes a required ``Idempotency-Key``.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Any

import pytest
from csmarket.core.ids import new_id
from csmarket.core.redis import get_redis
from csmarket.modules.admin.models import AdminAuditLog
from csmarket.modules.fx.api import record_snapshot
from csmarket.modules.skins import pricing_admin
from csmarket.modules.skins.cachekeys import CATALOG_VERSION_KEY
from csmarket.modules.skins.models import SkinItem, SkinPricingRules
from csmarket.modules.skins.pricing import DEFAULT_RULES
from csmarket.modules.skins.repricing import lock_pricing
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

Headers = Callable[[], Awaitable[dict[str, str]]]
RULES_KEY = "skins:pricing"
BASE = "/api/v1/admin/skins"


def _rules(**over: Any) -> dict[str, Any]:
    doc = json.loads(DEFAULT_RULES.model_dump_json())
    doc.update(over)
    return doc


async def _items(db: AsyncSession) -> None:
    for slug, units, cat, weapon in (
        ("ak-47-redline-ft", 10_000, "rifles", "AK-47"),
        ("awp-asiimov-ft", 50_000, "rifles", "AWP"),
        ("sticker-crown-foil", 2_000, "stickers", None),
    ):
        db.add(
            SkinItem(
                id=new_id(),
                market_hash_name=slug,
                phase="",
                slug=slug,
                category=cat,
                weapon=weapon,
                search_text=slug.replace("-", " "),
                active=True,
                min_auto_units=units,
                count_auto=5,
                sell_price_usd=Decimal("1.00"),
                cheapest_auto=[{"listing_id": 1, "price_units": units}],
                source="bymykel",
            )
        )
    await record_snapshot(db, rate=Decimal("12700"), source="cbu")
    await db.commit()


async def _prices(db: AsyncSession) -> dict[str, Decimal | None]:
    db.expire_all()
    rows = await db.execute(select(SkinItem.slug, SkinItem.sell_price_usd))
    return {slug: price for slug, price in rows}


async def _audits(db: AsyncSession, action: str) -> int:
    n = await db.scalar(
        select(func.count()).select_from(AdminAuditLog).where(AdminAuditLog.action == action)
    )
    return int(n or 0)


async def _put_rules(
    c: AsyncClient, headers: dict[str, str], doc: dict[str, Any], key: str = "pricing-key-000001"
) -> Any:
    return await c.put(f"{BASE}/pricing", json=doc, headers=headers | {"Idempotency-Key": key})


async def test_get_shows_the_live_rules_and_counts(
    integration_client: AsyncClient, db_session: AsyncSession, admin_headers: Headers
) -> None:
    await _items(db_session)
    r = await integration_client.get(f"{BASE}/pricing", headers=await admin_headers())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["rules"]["expenses_percent"] == "3"
    assert (body["items_active"], body["items_overridden"]) == (3, 0)
    assert Decimal(body["rate_uzs"]) == 12700
    assert body["updated_by"] is None


async def test_save_reprices_every_item_and_publishes_after_commit(
    integration_client: AsyncClient, db_session: AsyncSession, admin_headers: Headers
) -> None:
    await _items(db_session)
    headers = await admin_headers()
    version = await get_redis().get(CATALOG_VERSION_KEY)
    r = await _put_rules(integration_client, headers, _rules(expenses_percent="10"))
    assert r.status_code == 200, r.text
    assert r.json()["rules"]["expenses_percent"] == "10"
    assert r.json()["updated_by"]["id"]
    prices = await _prices(db_session)
    # cost 10 + expenses 10 % (1.00) + brackets (10 % of 1 + 5 % of 9 = 0.55)
    assert prices["ak-47-redline-ft"] == Decimal("11.55")
    assert all(p is not None and p != Decimal("1.00") for p in prices.values())
    raw = await get_redis().get(RULES_KEY)
    assert raw is not None
    assert json.loads(raw)["expenses_percent"] == "10"
    assert await get_redis().get(CATALOG_VERSION_KEY) != version
    assert await _audits(db_session, "skins.pricing.save") == 1


async def test_invalid_rules_answer_422_with_the_reason(
    integration_client: AsyncClient, db_session: AsyncSession, admin_headers: Headers
) -> None:
    await _items(db_session)
    doc = _rules(retail=[{"from_usd": "5", "percent": "10"}])
    r = await _put_rules(integration_client, await admin_headers(), doc)
    assert r.status_code == 422
    assert "first bracket must start at 0" in r.text


async def test_failed_save_keeps_old_rules_and_cache(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    admin_headers: Headers,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _items(db_session)
    headers = await admin_headers()
    assert (
        await _put_rules(integration_client, headers, _rules(expenses_percent="4"))
    ).status_code == 200
    before = await _prices(db_session)
    cached = await get_redis().get(RULES_KEY)
    version = await get_redis().get(CATALOG_VERSION_KEY)

    async def boom(*_a: object, **_k: object) -> int:
        raise RuntimeError("reprice failed")

    monkeypatch.setattr(pricing_admin, "reprice_rows", boom)
    try:
        r = await _put_rules(
            integration_client, headers, _rules(expenses_percent="9"), "pricing-key-000002"
        )
        assert r.status_code >= 500
    except RuntimeError:
        pass
    db_session.expire_all()
    row = await db_session.get(SkinPricingRules, 1)
    assert row is not None
    assert row.rules["expenses_percent"] == "4"
    assert await _prices(db_session) == before
    assert await get_redis().get(RULES_KEY) == cached
    assert await get_redis().get(CATALOG_VERSION_KEY) == version
    assert await _audits(db_session, "skins.pricing.save") == 1


async def test_a_replayed_key_answers_again_and_writes_once(
    integration_client: AsyncClient, db_session: AsyncSession, admin_headers: Headers
) -> None:
    await _items(db_session)
    headers = await admin_headers()
    first = await _put_rules(integration_client, headers, _rules(expenses_percent="5"))
    again = await _put_rules(integration_client, headers, _rules(expenses_percent="5"))
    assert (first.status_code, again.status_code) == (200, 200)
    assert first.json() == again.json()
    assert await _audits(db_session, "skins.pricing.save") == 1
    other = await _put_rules(integration_client, headers, _rules(expenses_percent="6"))
    assert (other.status_code, other.json()["code"]) == (409, "idempotency_mismatch")


async def test_writes_need_a_key(
    integration_client: AsyncClient, db_session: AsyncSession, admin_headers: Headers
) -> None:
    await _items(db_session)
    r = await integration_client.put(
        f"{BASE}/pricing", json=_rules(), headers=await admin_headers()
    )
    assert r.status_code == 422


async def test_preview_writes_nothing(
    integration_client: AsyncClient, db_session: AsyncSession, admin_headers: Headers
) -> None:
    await _items(db_session)
    headers = await admin_headers()
    await get_redis().delete(RULES_KEY)
    version = await get_redis().get(CATALOG_VERSION_KEY)
    before = await _prices(db_session)
    r = await integration_client.post(
        f"{BASE}/pricing/preview",
        json={"rules": _rules(expenses_percent="20"), "slug": "ak-47-redline-ft"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert await db_session.get(SkinPricingRules, 1) is None
    assert await get_redis().get(RULES_KEY) is None
    assert await get_redis().get(CATALOG_VERSION_KEY) == version
    assert await _prices(db_session) == before
    assert await _audits(db_session, "skins.pricing.save") == 0


async def test_preview_with_draft_rules_differs_from_the_saved_ones(
    integration_client: AsyncClient, db_session: AsyncSession, admin_headers: Headers
) -> None:
    await _items(db_session)
    headers = await admin_headers()
    body = {"cost_usd": "10", "category": "rifles", "weapon": "AK-47", "count_auto": 5}
    saved = (
        await integration_client.post(f"{BASE}/pricing/preview", json=body, headers=headers)
    ).json()
    draft = (
        await integration_client.post(
            f"{BASE}/pricing/preview",
            json=body | {"rules": _rules(expenses_percent="20")},
            headers=headers,
        )
    ).json()
    assert Decimal(draft["price_usd"]) > Decimal(saved["price_usd"])
    assert saved["cost_usd"] == "10"
    assert saved["applied"] == "formula"
    assert saved["price_uzs"] == str(
        (Decimal(saved["price_usd"]) * 12700 / 100).to_integral_value(rounding="ROUND_CEILING")
        * 100
    )


async def test_preview_needs_a_slug_or_a_cost_and_category(
    integration_client: AsyncClient, db_session: AsyncSession, admin_headers: Headers
) -> None:
    await _items(db_session)
    headers = await admin_headers()
    for body in ({}, {"cost_usd": "10"}, {"category": "rifles"}):
        r = await integration_client.post(f"{BASE}/pricing/preview", json=body, headers=headers)
        assert r.status_code == 422, body
    r = await integration_client.post(
        f"{BASE}/pricing/preview", json={"slug": "no-such-skin"}, headers=headers
    )
    assert r.status_code == 404


async def test_override_sets_and_clears_one_item_only(
    integration_client: AsyncClient, db_session: AsyncSession, admin_headers: Headers
) -> None:
    await _items(db_session)
    headers = await admin_headers()
    before = await _prices(db_session)
    url = f"{BASE}/items/awp-asiimov-ft/pricing"
    r = await integration_client.put(
        url,
        json={"margin_override_pp": "10", "fixed_price_usd": None},
        headers=headers | {"Idempotency-Key": "override-key-0000001"},
    )
    assert r.status_code == 200, r.text
    assert (r.json()["margin_override_pp"], r.json()["fixed_price_usd"]) == ("10", None)
    assert r.json()["cost_usd"] == "50"
    after = await _prices(db_session)
    assert after["awp-asiimov-ft"] != before["awp-asiimov-ft"]
    assert after["ak-47-redline-ft"] == before["ak-47-redline-ft"]  # untouched
    preview = await integration_client.post(
        f"{BASE}/pricing/preview", json={"slug": "awp-asiimov-ft"}, headers=headers
    )
    assert preview.json()["item_pp"] == "10"
    assert Decimal(preview.json()["price_usd"]) == after["awp-asiimov-ft"]
    listed = await integration_client.get(f"{BASE}/items?overridden=true", headers=headers)
    assert [i["slug"] for i in listed.json()["items"]] == ["awp-asiimov-ft"]
    cleared = await integration_client.put(
        url,
        json={"margin_override_pp": None, "fixed_price_usd": "99.50"},
        headers=headers | {"Idempotency-Key": "override-key-0000002"},
    )
    assert (cleared.json()["margin_override_pp"], cleared.json()["fixed_price_usd"]) == (
        None,
        "99.50",
    )
    assert (await _prices(db_session))["awp-asiimov-ft"] == Decimal("99.50")
    assert await _audits(db_session, "skins.item.override") == 2


@pytest.mark.parametrize(
    "body",
    [{"margin_override_pp": "-101"}, {"margin_override_pp": "1.234"}, {"fixed_price_usd": "-1"}],
)
async def test_override_bounds(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    admin_headers: Headers,
    body: dict[str, str],
) -> None:
    await _items(db_session)
    r = await integration_client.put(
        f"{BASE}/items/awp-asiimov-ft/pricing",
        json={"margin_override_pp": None, "fixed_price_usd": None} | body,
        headers=await admin_headers() | {"Idempotency-Key": "override-key-0000003"},
    )
    assert r.status_code == 422


async def test_a_save_waits_for_a_running_price_tick(
    integration_client: AsyncClient, db_session: AsyncSession, admin_headers: Headers
) -> None:
    await _items(db_session)
    headers = await admin_headers()
    factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)
    async with factory() as tick:
        await lock_pricing(tick)  # the price sync holds the lock for its transaction
        save = asyncio.create_task(
            _put_rules(integration_client, headers, _rules(expenses_percent="7"))
        )
        await asyncio.sleep(0.3)
        assert not save.done()
        await tick.commit()
    r = await asyncio.wait_for(save, timeout=10)
    assert r.status_code == 200


async def test_customers_are_refused(
    integration_client: AsyncClient, customer_headers: Headers
) -> None:
    headers = await customer_headers()
    assert (await integration_client.get(f"{BASE}/pricing", headers=headers)).status_code == 403
    r = await integration_client.post(
        f"{BASE}/pricing/preview", json={"cost_usd": "1", "category": "rifles"}, headers=headers
    )
    assert r.status_code == 403
