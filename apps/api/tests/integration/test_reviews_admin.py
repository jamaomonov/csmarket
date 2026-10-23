"""``/admin/reviews*``: the tabs, «Разобрано», hide / show and the switch — audited, and no
review text in any audit payload."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from datetime import timedelta
from uuid import uuid4

import pytest
from csmarket.core.clock import now
from csmarket.modules.admin.models import AdminAuditLog
from csmarket.modules.reviews import admin as reviews_admin
from csmarket.modules.users.models import User
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.conftest import ADMIN_STEAM_ID
from tests.integration.reviews_factory import (
    credited_sale,
    delivered_order,
    make_review,
    set_public,
)

pytestmark = pytest.mark.asyncio

Headers = Callable[[], Awaitable[dict[str, str]]]
BASE = "/api/v1/admin/reviews"


def _key() -> dict[str, str]:
    return {"Idempotency-Key": f"test-admin-review-{uuid4()}"}


async def _admin(db: AsyncSession, admin_headers: Headers) -> tuple[dict[str, str], str]:
    h = await admin_headers()
    admin_id = await db.scalar(select(User.id).where(User.steam_id == ADMIN_STEAM_ID))
    assert admin_id is not None
    return h, admin_id


async def _audit(db: AsyncSession, action: str) -> list[AdminAuditLog]:
    db.expire_all()
    q = select(AdminAuditLog).where(AdminAuditLog.action == action)
    return list((await db.scalars(q)).all())


async def test_tabs_and_filters(
    db_session: AsyncSession, integration_client: AsyncClient, admin_headers: Headers
) -> None:
    h, admin_id = await _admin(db_session, admin_headers)
    at = now()
    sale = await credited_sale(db_session)
    resolved = await make_review(
        db_session,
        deal=await delivered_order(db_session),
        rating=1,
        created_at=at,
        resolved_at=at,
        resolved_by=admin_id,
        resolved_note="Помогли",
    )
    old_bad = await make_review(
        db_session,
        deal=await delivered_order(db_session),
        rating=3,
        created_at=at - timedelta(hours=2),
    )
    new_bad = await make_review(
        db_session, deal=sale, rating=2, locale="uz", created_at=at - timedelta(hours=1)
    )
    good = await make_review(
        db_session,
        deal=await delivered_order(db_session),
        rating=4,
        locale="en",
        created_at=at + timedelta(minutes=1),
    )

    async def listed(**params: str) -> list[str]:
        r = await integration_client.get(BASE, params=params, headers=h)
        assert r.status_code == 200, r.text
        return [i["id"] for i in r.json()["items"]]

    # «Плохие»: unresolved first, newest first within each group.
    assert await listed() == [new_bad.id, old_bad.id, resolved.id]
    assert await listed(tab="good") == [good.id]
    assert await listed(tab="all") == [good.id, resolved.id, new_bad.id, old_bad.id]
    assert await listed(tab="all", kind="sale") == [new_bad.id]
    assert await listed(tab="all", locale="en") == [good.id]
    page = (await integration_client.get(BASE, headers=h)).json()
    assert page["bad_open"] == 2
    first = page["items"][0]
    assert (first["kind"], first["number"], first["published"]) == ("sale", sale.number, False)
    assert first["user"]["id"] == sale.user_id
    assert page["items"][2]["resolved_by"]["id"] == admin_id
    assert (
        await integration_client.get(BASE, params={"tab": "worst"}, headers=h)
    ).status_code == 422


async def test_the_bad_tab_pages_across_the_resolved_boundary(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    admin_headers: Headers,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(reviews_admin, "PAGE", 2)
    h, admin_id = await _admin(db_session, admin_headers)
    at = now()
    a = await make_review(
        db_session, deal=await delivered_order(db_session), rating=2, created_at=at
    )
    b = await make_review(
        db_session,
        deal=await delivered_order(db_session),
        rating=2,
        created_at=at - timedelta(hours=1),
    )
    c = await make_review(
        db_session,
        deal=await delivered_order(db_session),
        rating=2,
        created_at=at + timedelta(hours=1),
        resolved_at=at,
        resolved_by=admin_id,
        resolved_note="ok",
    )
    first = (await integration_client.get(BASE, headers=h)).json()
    assert [i["id"] for i in first["items"]] == [a.id, b.id]
    assert first["next_cursor"]
    rest = (
        await integration_client.get(BASE, params={"cursor": first["next_cursor"]}, headers=h)
    ).json()
    assert [i["id"] for i in rest["items"]] == [c.id]
    assert rest["next_cursor"] is None


async def test_resolve_once_without_the_text_in_the_audit(
    db_session: AsyncSession, integration_client: AsyncClient, admin_headers: Headers
) -> None:
    h, admin_id = await _admin(db_session, admin_headers)
    order = await delivered_order(db_session)
    number = order.number
    rid = (await make_review(db_session, deal=order, rating=2, text="Секретный текст")).id
    url = f"{BASE}/{rid}/resolve"
    r = await integration_client.post(
        url, json={"note": "  Позвонили, вернули  "}, headers={**h, **_key()}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["resolved_note"], body["resolved_by"]["id"], body["number"]) == (
        "Позвонили, вернули",
        admin_id,
        number,
    )
    again = await integration_client.post(url, json={"note": "ещё раз"}, headers={**h, **_key()})
    assert again.json()["resolved_note"] == "Позвонили, вернули"
    [row] = await _audit(db_session, "reviews.review.resolve")
    assert (row.target_type, row.target_id) == ("review", rid)
    assert row.payload == {"kind": "market", "number": number, "rating": 2}
    assert "Секретный" not in json.dumps(row.payload, ensure_ascii=False)


async def test_resolve_refuses_a_good_or_unknown_review_and_a_blank_note(
    db_session: AsyncSession, integration_client: AsyncClient, admin_headers: Headers
) -> None:
    h, _ = await _admin(db_session, admin_headers)
    good = (await make_review(db_session, deal=await delivered_order(db_session), rating=4)).id
    r = await integration_client.post(
        f"{BASE}/{good}/resolve", json={"note": "x"}, headers={**h, **_key()}
    )
    assert (r.status_code, r.json()["code"]) == (409, "review_not_bad")
    for rid in (str(uuid4()), "not-a-uuid"):
        r = await integration_client.post(
            f"{BASE}/{rid}/resolve", json={"note": "x"}, headers={**h, **_key()}
        )
        assert (r.status_code, r.json()["code"]) == (404, "review_not_found")
    blank = await integration_client.post(
        f"{BASE}/{good}/resolve", json={"note": "   "}, headers={**h, **_key()}
    )
    assert blank.status_code == 422


async def test_hide_and_show_audited_and_off_the_public_page(
    db_session: AsyncSession, integration_client: AsyncClient, admin_headers: Headers
) -> None:
    h, _ = await _admin(db_session, admin_headers)
    await set_public(db_session)
    rid = (await make_review(db_session, deal=await delivered_order(db_session), rating=5)).id
    hidden = await integration_client.post(f"{BASE}/{rid}/hide", headers={**h, **_key()})
    assert (hidden.json()["hidden"], hidden.json()["published"]) == (True, False)
    assert (await integration_client.get("/api/v1/reviews")).json()["count"] == 0
    shown = await integration_client.post(f"{BASE}/{rid}/unhide", headers={**h, **_key()})
    assert (shown.json()["hidden"], shown.json()["published"]) == (False, True)
    assert len(await _audit(db_session, "reviews.review.hide")) == 1
    assert len(await _audit(db_session, "reviews.review.unhide")) == 1


async def test_the_switch(
    db_session: AsyncSession, integration_client: AsyncClient, admin_headers: Headers
) -> None:
    h, admin_id = await _admin(db_session, admin_headers)
    await make_review(db_session, deal=await delivered_order(db_session), rating=5)
    await make_review(db_session, deal=await delivered_order(db_session), rating=2)
    view = (await integration_client.get(f"{BASE}/settings", headers=h)).json()
    assert (view["reviews_public"], view["published_count"], view["updated_by"]) == (
        False,
        1,
        None,
    )
    key = _key()
    on = await integration_client.put(
        f"{BASE}/settings", json={"reviews_public": True}, headers={**h, **key}
    )
    again = await integration_client.put(
        f"{BASE}/settings", json={"reviews_public": True}, headers={**h, **key}
    )
    assert on.status_code == 200
    assert on.json() == again.json()
    assert (on.json()["reviews_public"], on.json()["updated_by"]["id"]) == (True, admin_id)
    [row] = await _audit(db_session, "reviews.settings.save")
    assert (row.target_type, row.payload) == ("review_settings", {"enabled": True})
    assert (await integration_client.get("/api/v1/reviews")).json()["enabled"] is True
    other = await integration_client.put(
        f"{BASE}/settings", json={"reviews_public": False}, headers={**h, **key}
    )
    assert (other.status_code, other.json()["code"]) == (409, "idempotency_mismatch")
    bare = await integration_client.put(
        f"{BASE}/settings", json={"reviews_public": False}, headers=h
    )
    assert bare.status_code == 422


async def test_customers_cannot_touch_it(
    integration_client: AsyncClient, customer_headers: Headers
) -> None:
    h = await customer_headers()
    assert (await integration_client.get(BASE, headers=h)).status_code == 403
    r = await integration_client.put(
        f"{BASE}/settings", json={"reviews_public": True}, headers={**h, **_key()}
    )
    assert r.status_code == 403


async def test_the_dashboard_counts_unresolved_bad_reviews(
    db_session: AsyncSession, integration_client: AsyncClient, admin_headers: Headers
) -> None:
    h, admin_id = await _admin(db_session, admin_headers)
    await make_review(db_session, deal=await delivered_order(db_session), rating=1)
    await make_review(db_session, deal=await delivered_order(db_session), rating=3)
    await make_review(db_session, deal=await delivered_order(db_session), rating=5)
    await make_review(
        db_session,
        deal=await delivered_order(db_session),
        rating=2,
        resolved_at=now(),
        resolved_by=admin_id,
        resolved_note="ok",
    )
    r = await integration_client.get("/api/v1/admin/dashboard", headers=h)
    assert r.json()["reviews_bad_open"] == 2
