"""Admin catalogue: status, hide/unhide, aliases (rulings Q4–Q6, Review Focus 4)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from decimal import Decimal

from csmarket.core.ids import new_id
from csmarket.modules.admin.models import AdminAuditLog
from csmarket.modules.fx.api import record_snapshot
from csmarket.modules.skins.job_status import JOB_IMPORT, record_job
from csmarket.modules.skins.models import SkinItem, SkinSearchAlias
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

KEY = "admin-catalogue-key-0001"
Headers = Callable[[], Awaitable[dict[str, str]]]


async def _family(db: AsyncSession) -> None:
    for ext, usd in (("FT", "10.00"), ("MW", "12.00")):
        db.add(
            SkinItem(
                id=new_id(),
                market_hash_name=f"AK-47 | Redline ({ext})",
                phase="",
                slug=f"ak-47-redline-{ext.lower()}",
                category="rifles",
                weapon="AK-47",
                skin="Redline",
                exterior=ext,
                search_text=f"ak 47 redline {ext.lower()}",
                active=True,
                min_auto_units=int(Decimal(usd) * 900),
                count_auto=5,
                sell_price_usd=Decimal(usd),
                cheapest_auto=[{"listing_id": 1, "price_units": int(Decimal(usd) * 900)}],
                source="bymykel",
            )
        )
    await record_snapshot(db, rate=Decimal("12700"), source="cbu")
    await db.commit()


async def _visible(c: AsyncClient) -> dict[str, object]:
    cat = {i["slug"] for i in (await c.get("/api/v1/skins/catalog")).json()["items"]}
    sug = {
        i["slug"]
        for i in (await c.get("/api/v1/skins/suggest", params={"q": "redline"})).json()["items"]
    }
    seo = set((await c.get("/api/v1/skins/seo/slugs")).json()["items"])
    facets = (await c.get("/api/v1/skins/facets")).json()["categories"]
    rifles = {f["value"]: f["count"] for f in facets}
    fam = {m["slug"] for m in (await c.get("/api/v1/skins/ak-47-redline-ft")).json()["family"]}
    detail = (await c.get("/api/v1/skins/ak-47-redline-mw")).status_code
    return {
        "cat": cat,
        "sug": sug,
        "seo": seo,
        "rifles": rifles.get("rifles"),
        "fam": fam,
        "detail": detail,
    }


async def _hide(c: AsyncClient, headers: dict[str, str], hidden: bool, key: str) -> object:
    return await c.patch(
        "/api/v1/admin/skins/items/ak-47-redline-mw",
        json={"hidden": hidden},
        headers=headers | {"Idempotency-Key": key},
    )


async def test_hide_hides_everywhere_and_unhide_restores(
    integration_client: AsyncClient, db_session: AsyncSession, admin_headers: Headers
) -> None:
    await _family(db_session)
    before = await _visible(integration_client)  # also warms the 60 s page cache
    assert isinstance(before["cat"], set)
    assert "ak-47-redline-mw" in before["cat"]
    assert before["rifles"] == 2
    assert before["detail"] == 200

    r = await integration_client.patch(
        "/api/v1/admin/skins/items/ak-47-redline-mw",
        json={"hidden": True},
        headers=await admin_headers() | {"Idempotency-Key": KEY},
    )
    assert r.status_code == 200
    assert r.json()["hidden"] is True
    hidden = await _visible(integration_client)
    seen: set[str] = set()
    for part in ("cat", "sug", "seo", "fam"):
        value = hidden[part]
        assert isinstance(value, set)
        seen |= value
    assert "ak-47-redline-mw" not in seen
    assert hidden["rifles"] == 1
    assert hidden["detail"] == 404

    r = await integration_client.patch(
        "/api/v1/admin/skins/items/ak-47-redline-mw",
        json={"hidden": False},
        headers=await admin_headers() | {"Idempotency-Key": KEY + "-un"},
    )
    assert r.status_code == 200
    assert r.json()["hidden"] is False
    assert await _visible(integration_client) == before

    rows = (
        await db_session.execute(select(AdminAuditLog).order_by(AdminAuditLog.created_at))
    ).scalars()
    audit = [(a.action, a.target_type, a.payload) for a in rows]
    assert audit == [
        ("skins.item.hide", "skin_item", {"slug": "ak-47-redline-mw"}),
        ("skins.item.unhide", "skin_item", {"slug": "ak-47-redline-mw"}),
    ]


async def test_a_customer_cannot_hide(
    integration_client: AsyncClient, db_session: AsyncSession, customer_headers: Headers
) -> None:
    await _family(db_session)
    r = await integration_client.patch(
        "/api/v1/admin/skins/items/ak-47-redline-mw",
        json={"hidden": True},
        headers=await customer_headers() | {"Idempotency-Key": KEY},
    )
    assert r.status_code == 403


async def test_no_token_is_401(integration_client: AsyncClient) -> None:
    r = await integration_client.get("/api/v1/admin/skins/catalog/status")
    assert r.status_code == 401


async def test_replayed_hide_writes_one_audit_row(
    integration_client: AsyncClient, db_session: AsyncSession, admin_headers: Headers
) -> None:
    await _family(db_session)
    h = await admin_headers() | {"Idempotency-Key": KEY}
    for _ in range(2):
        r = await integration_client.patch(
            "/api/v1/admin/skins/items/ak-47-redline-mw", json={"hidden": True}, headers=h
        )
        assert r.status_code == 200
        assert r.json()["hidden"] is True
    assert len((await db_session.execute(select(AdminAuditLog))).scalars().all()) == 1


async def test_unknown_slug_is_404(
    integration_client: AsyncClient, db_session: AsyncSession, admin_headers: Headers
) -> None:
    r = await integration_client.patch(
        "/api/v1/admin/skins/items/no-such-item",
        json={"hidden": True},
        headers=await admin_headers() | {"Idempotency-Key": KEY},
    )
    assert r.status_code == 404
    assert (await db_session.execute(select(AdminAuditLog))).scalars().all() == []


async def test_alias_put_search_delete(
    integration_client: AsyncClient, db_session: AsyncSession, admin_headers: Headers
) -> None:
    await _family(db_session)
    h = await admin_headers()
    r = await integration_client.put(
        "/api/v1/admin/skins/aliases/РЕДЛАЙН",
        json={"text": "Redline"},
        headers=h | {"Idempotency-Key": KEY},
    )
    assert r.status_code == 200
    assert r.json() == {"alias": "редлайн", "text": "redline"}
    found = (await integration_client.get("/api/v1/skins/catalog", params={"q": "редлайн"})).json()[
        "items"
    ]
    assert {i["slug"] for i in found} == {"ak-47-redline-ft", "ak-47-redline-mw"}
    listed = (await integration_client.get("/api/v1/admin/skins/aliases", headers=h)).json()
    assert listed["items"] == [{"alias": "редлайн", "text": "redline"}]
    r = await integration_client.delete(
        "/api/v1/admin/skins/aliases/редлайн", headers=h | {"Idempotency-Key": KEY + "-d"}
    )
    assert r.status_code == 204
    gone = await integration_client.get("/api/v1/skins/catalog", params={"q": "редлайн"})
    assert gone.json()["items"] == []

    rows = (
        await db_session.execute(select(AdminAuditLog).order_by(AdminAuditLog.created_at))
    ).scalars()
    audit = [(a.action, a.target_type, a.target_id, a.payload) for a in rows]
    assert audit == [
        ("skins.alias.put", "skin_alias", "редлайн", {"alias": "редлайн", "text": "redline"}),
        ("skins.alias.delete", "skin_alias", "редлайн", {"alias": "редлайн"}),
    ]


async def test_alias_put_overwrites_and_replay_writes_once(
    integration_client: AsyncClient, db_session: AsyncSession, admin_headers: Headers
) -> None:
    h = await admin_headers()
    for _ in range(2):
        r = await integration_client.put(
            "/api/v1/admin/skins/aliases/ак",
            json={"text": "AK-47"},
            headers=h | {"Idempotency-Key": KEY},
        )
        assert r.json() == {"alias": "ак", "text": "ak-47"}
    r = await integration_client.put(
        "/api/v1/admin/skins/aliases/ак",
        json={"text": "  AK 47  "},
        headers=h | {"Idempotency-Key": KEY + "-2"},
    )
    assert r.json() == {"alias": "ак", "text": "ak 47"}
    rows = (await db_session.execute(select(SkinSearchAlias))).scalars().all()
    assert [(a.alias, a.text) for a in rows] == [("ак", "ak 47")]
    assert len((await db_session.execute(select(AdminAuditLog))).scalars().all()) == 2


async def test_delete_unknown_alias_is_404(
    integration_client: AsyncClient, admin_headers: Headers
) -> None:
    r = await integration_client.delete(
        "/api/v1/admin/skins/aliases/nothing", headers=await admin_headers()
    )
    assert r.status_code == 404


async def test_bad_alias_is_422(integration_client: AsyncClient, admin_headers: Headers) -> None:
    h = await admin_headers() | {"Idempotency-Key": KEY}
    for alias in ("a_b", "a.b", "x" * 65):
        r = await integration_client.put(
            f"/api/v1/admin/skins/aliases/{alias}", json={"text": "x"}, headers=h
        )
        assert r.status_code == 422, alias
    for text in ("", "   ", "y" * 129):
        r = await integration_client.put(
            "/api/v1/admin/skins/aliases/ok", json={"text": text}, headers=h
        )
        assert r.status_code == 422, text


async def test_admin_item_search(
    integration_client: AsyncClient, db_session: AsyncSession, admin_headers: Headers
) -> None:
    await _family(db_session)
    h = await admin_headers()
    r = await integration_client.get(
        "/api/v1/admin/skins/items", params={"q": "Redline (MW)"}, headers=h
    )
    assert [i["slug"] for i in r.json()["items"]] == ["ak-47-redline-mw"]
    item = r.json()["items"][0]
    assert item["price_usd"] == "12.00"
    assert item["hidden"] is False
    assert item["active"] is True
    assert set(item) == {
        "slug",
        "name",
        "phase",
        "category",
        "weapon",
        "exterior",
        "stattrak",
        "souvenir",
        "image_url",
        "active",
        "hidden",
        "price_usd",
        "count",
    }
    await _hide(integration_client, await admin_headers(), True, KEY)
    hidden = await integration_client.get(
        "/api/v1/admin/skins/items", params={"q": "redline", "hidden": "true"}, headers=h
    )
    assert [i["slug"] for i in hidden.json()["items"]] == ["ak-47-redline-mw"]
    shown = await integration_client.get(
        "/api/v1/admin/skins/items", params={"q": "redline", "hidden": "false"}, headers=h
    )
    assert [i["slug"] for i in shown.json()["items"]] == ["ak-47-redline-ft"]
    # ``%`` and ``_`` are literals, not wildcards.
    wild = await integration_client.get("/api/v1/admin/skins/items", params={"q": "%%"}, headers=h)
    assert wild.json()["items"] == []
    short = await integration_client.get("/api/v1/admin/skins/items", params={"q": "a"}, headers=h)
    assert short.status_code == 422


async def test_status(
    integration_client: AsyncClient, db_session: AsyncSession, admin_headers: Headers
) -> None:
    await _family(db_session)
    path = "/api/v1/admin/skins/catalog/status"
    body = (await integration_client.get(path, headers=await admin_headers())).json()
    assert (body["items_total"], body["items_active"], body["items_hidden"]) == (2, 2, 0)
    assert body["fx"]["usd_uzs"] == "12700.0000"
    assert body["sync_enabled"] is False
    assert body["fx"]["source"] == "cbu"
    assert body["import_job"] is None
    assert body["price_sync_job"] is None
    assert body["waxpeer_key_set"] is False
    assert body["prices_updated_at"] is None


async def test_status_reports_the_last_job(
    integration_client: AsyncClient, admin_headers: Headers
) -> None:
    from csmarket.core.redis import get_redis

    await record_job(get_redis(), JOB_IMPORT, ok=False, counters={"seen": 3}, error="http")
    path = "/api/v1/admin/skins/catalog/status"
    body = (await integration_client.get(path, headers=await admin_headers())).json()
    job = body["import_job"]
    assert (job["ok"], job["counters"], job["error"]) == (False, {"seen": 3}, "http")
    assert job["finished_at"]
    assert body["fx"] is None
    assert body["items_total"] == 0
