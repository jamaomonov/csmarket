"""A user's own review of their own deal: write, read, replay, limits, «Не сейчас» and ×.

ORM objects are read into plain values before ``_rows``: it expires the session, and an async
session cannot lazy-load an expired attribute.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import timedelta
from uuid import uuid4

import pytest
from csmarket.core import config as cfg
from csmarket.core.clock import now
from csmarket.modules.reviews.models import Review, ReviewPrompt
from csmarket.modules.sales.models import SaleItem
from csmarket.modules.skins.models import SkinItem
from csmarket.modules.users.models import User
from httpx import AsyncClient, Response
from prometheus_client import REGISTRY
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.conftest import CUSTOMER_STEAM_ID
from tests.integration.payments_factory import make_user
from tests.integration.reviews_factory import credited_sale, delivered_order, make_review

pytestmark = pytest.mark.asyncio

Headers = Callable[[], Awaitable[dict[str, str]]]
BASE = "/api/v1/reviews"


def _key() -> dict[str, str]:
    return {"Idempotency-Key": f"test-review-{uuid4()}"}


async def _me(db: AsyncSession, customer_headers: Headers) -> tuple[dict[str, str], User]:
    headers = await customer_headers()
    user = await db.scalar(select(User).where(User.steam_id == CUSTOMER_STEAM_ID))
    assert user is not None
    return headers, user


def _count(kind: str, rating: str) -> float:
    labels = {"kind": kind, "rating": rating}
    return REGISTRY.get_sample_value("csmarket_reviews_total", labels) or 0.0


async def _rows(db: AsyncSession) -> list[Review]:
    db.expire_all()
    return list((await db.scalars(select(Review))).all())


async def _put(
    c: AsyncClient, path: str, body: dict[str, object], headers: dict[str, str]
) -> Response:
    return await c.put(f"{BASE}/{path}", json=body, headers={**headers, **_key()})


async def test_write_a_review_and_read_it_back(
    db_session: AsyncSession, integration_client: AsyncClient, customer_headers: Headers
) -> None:
    headers, me = await _me(db_session, customer_headers)
    number = (await delivered_order(db_session, user=me)).number
    before = _count("market", "5")
    r = await _put(
        integration_client,
        f"market/{number}",
        {"rating": 5, "text": "Быстро, спасибо", "locale": "uz"},
        headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["kind"], body["number"], body["can_review"]) == ("market", number, True)
    assert (body["review"]["rating"], body["review"]["locale"]) == (5, "uz")
    assert body["review"]["text"] == "Быстро, спасибо"
    got = await integration_client.get(f"{BASE}/market/{number}", headers=headers)
    assert got.json() == body
    assert _count("market", "5") == before + 1


async def test_text_is_trimmed_and_blank_is_null(
    db_session: AsyncSession, integration_client: AsyncClient, customer_headers: Headers
) -> None:
    headers, me = await _me(db_session, customer_headers)
    a = (await delivered_order(db_session, user=me)).number
    b = (await delivered_order(db_session, user=me)).number
    r1 = await _put(
        integration_client,
        f"market/{a}",
        {"rating": 4, "text": "  <b>hi</b>  ", "locale": "ru"},
        headers,
    )
    r2 = await _put(
        integration_client, f"market/{b}", {"rating": 4, "text": "   ", "locale": "ru"}, headers
    )
    assert r1.json()["review"]["text"] == "<b>hi</b>"
    assert r2.json()["review"]["text"] is None


@pytest.mark.parametrize(
    "body",
    [
        {"rating": 0, "locale": "ru"},
        {"rating": 6, "locale": "ru"},
        {"rating": 5, "locale": "de"},
        {"rating": 5, "locale": "ru", "text": "x" * 1001},
    ],
)
async def test_bad_input_is_422(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    customer_headers: Headers,
    body: dict[str, object],
) -> None:
    headers, me = await _me(db_session, customer_headers)
    number = (await delivered_order(db_session, user=me)).number
    r = await _put(integration_client, f"market/{number}", body, headers)
    assert r.status_code == 422


async def test_a_thousand_characters_fit(
    db_session: AsyncSession, integration_client: AsyncClient, customer_headers: Headers
) -> None:
    headers, me = await _me(db_session, customer_headers)
    number = (await delivered_order(db_session, user=me)).number
    body = {"rating": 2, "text": "я" * 1000 + "   ", "locale": "ru"}
    r = await _put(integration_client, f"market/{number}", body, headers)
    assert r.status_code == 200
    assert len(r.json()["review"]["text"]) == 1000


async def test_someone_elses_or_an_unknown_deal_is_404(
    db_session: AsyncSession, integration_client: AsyncClient, customer_headers: Headers
) -> None:
    headers, _ = await _me(db_session, customer_headers)
    theirs = (await delivered_order(db_session)).number
    for path in (f"market/{theirs}", "market/ZZZZZZZZ", "sale/SZZZZZZZ"):
        r = await _put(integration_client, path, {"rating": 5, "locale": "ru"}, headers)
        assert (r.status_code, r.json()["code"]) == (404, "deal_not_found"), path
        assert (await integration_client.get(f"{BASE}/{path}", headers=headers)).status_code == 404


async def test_a_deal_outside_the_rule_is_409(
    db_session: AsyncSession, integration_client: AsyncClient, customer_headers: Headers
) -> None:
    headers, me = await _me(db_session, customer_headers)
    sent = (
        await delivered_order(db_session, user=me, status="trade_sent", delivered_at=None)
    ).number
    old = (await delivered_order(db_session, user=me, days_ago=15)).number
    for number in (sent, old):
        r = await _put(
            integration_client, f"market/{number}", {"rating": 5, "locale": "ru"}, headers
        )
        assert (r.status_code, r.json()["code"]) == (409, "review_not_allowed")
    view = (await integration_client.get(f"{BASE}/market/{old}", headers=headers)).json()
    assert (view["can_review"], view["review"]) == (False, None)


async def test_an_edit_that_turns_bad_unpublishes_and_reopens(
    db_session: AsyncSession, integration_client: AsyncClient, customer_headers: Headers
) -> None:
    headers, me = await _me(db_session, customer_headers)
    admin_id = (await make_user(db_session)).id
    order = await delivered_order(db_session, user=me)
    number = order.number
    await make_review(db_session, deal=order, rating=5, text="ok")
    before = _count("market", "2")
    words = {"rating": 2, "text": "Долго ждал", "locale": "ru"}
    assert (await _put(integration_client, f"market/{number}", words, headers)).status_code == 200
    [row] = await _rows(db_session)
    assert (row.rating, row.text, row.resolved_at) == (2, "Долго ждал", None)
    assert _count("market", "2") == before  # an edit is not a new review
    row.resolved_at, row.resolved_by, row.resolved_note = now(), admin_id, "Позвонили"
    await db_session.commit()
    # The same words again leave it resolved; a changed bad review reopens.
    await _put(integration_client, f"market/{number}", words, headers)
    [row] = await _rows(db_session)
    assert row.resolved_at is not None
    await _put(integration_client, f"market/{number}", {**words, "rating": 1}, headers)
    [row] = await _rows(db_session)
    assert (row.rating, row.resolved_at, row.resolved_by, row.resolved_note) == (
        1,
        None,
        None,
        None,
    )


async def test_replay_answers_the_same_and_writes_once(
    db_session: AsyncSession, integration_client: AsyncClient, customer_headers: Headers
) -> None:
    headers, me = await _me(db_session, customer_headers)
    number = (await delivered_order(db_session, user=me)).number
    h = {**headers, **_key()}
    url = f"{BASE}/market/{number}"
    a = await integration_client.put(url, json={"rating": 5, "locale": "ru"}, headers=h)
    b = await integration_client.put(url, json={"rating": 5, "locale": "ru"}, headers=h)
    assert (a.status_code, b.status_code) == (200, 200)
    assert a.json() == b.json()
    assert len(await _rows(db_session)) == 1
    c = await integration_client.put(url, json={"rating": 4, "locale": "ru"}, headers=h)
    assert (c.status_code, c.json()["code"]) == (409, "idempotency_mismatch")
    bare = await integration_client.put(url, json={"rating": 4, "locale": "ru"}, headers=headers)
    assert bare.status_code == 422


async def test_two_first_reviews_at_once_make_one_row(
    db_session: AsyncSession, integration_client: AsyncClient, customer_headers: Headers
) -> None:
    headers, me = await _me(db_session, customer_headers)
    number = (await delivered_order(db_session, user=me)).number
    a, b = await asyncio.gather(
        _put(integration_client, f"market/{number}", {"rating": 5, "locale": "ru"}, headers),
        _put(integration_client, f"market/{number}", {"rating": 4, "locale": "ru"}, headers),
    )
    assert (a.status_code, b.status_code) == (200, 200)
    assert len(await _rows(db_session)) == 1


async def test_writes_are_rate_limited(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    customer_headers: Headers,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A per-IP ceiling set for ``review`` trips at 2 (a typo'd bucket would not)."""
    monkeypatch.setenv("CSMARKET_AUTH_IP_GUARD_BUCKET_MAX", '{"review": 2}')
    cfg.get_settings.cache_clear()
    headers, me = await _me(db_session, customer_headers)
    number = (await delivered_order(db_session, user=me)).number
    h = {**headers, "X-Forwarded-For": "203.0.113.91"}
    for _ in range(2):
        r = await _put(integration_client, f"market/{number}", {"rating": 5, "locale": "ru"}, h)
        assert r.status_code == 200
    r = await _put(integration_client, f"market/{number}", {"rating": 5, "locale": "ru"}, h)
    assert r.status_code == 429


async def test_pending_snooze_and_dismiss(
    db_session: AsyncSession, integration_client: AsyncClient, customer_headers: Headers
) -> None:
    headers, me = await _me(db_session, customer_headers)
    older = (await delivered_order(db_session, user=me, days_ago=2)).number
    newer = (await credited_sale(db_session, user=me, days_ago=1)).number
    deal = (await integration_client.get(f"{BASE}/pending", headers=headers)).json()["deal"]
    assert set(deal) == {"kind", "number", "title", "image_url", "rarity_color", "items", "done_at"}
    assert (deal["kind"], deal["number"], deal["items"]) == ("sale", newer, 2)
    snoozed = await integration_client.post(
        f"{BASE}/sale/{newer}/snooze", headers={**headers, **_key()}
    )
    assert snoozed.status_code == 204
    deal = (await integration_client.get(f"{BASE}/pending", headers=headers)).json()["deal"]
    assert deal["number"] == older
    dismissed = await integration_client.post(
        f"{BASE}/market/{older}/dismiss", headers={**headers, **_key()}
    )
    assert dismissed.status_code == 204
    assert (await integration_client.get(f"{BASE}/pending", headers=headers)).json() == {
        "deal": None
    }
    prompts = list((await db_session.scalars(select(ReviewPrompt))).all())
    by_kind = {p.kind: p for p in prompts}
    until = by_kind["sale"].snoozed_until
    assert until is not None
    assert until > now() + timedelta(days=2, hours=23)
    assert by_kind["market"].dismissed is True
    bare = await integration_client.post(f"{BASE}/market/{older}/snooze", headers=headers)
    assert bare.status_code == 422


async def test_a_replayed_snooze_writes_once(
    db_session: AsyncSession, integration_client: AsyncClient, customer_headers: Headers
) -> None:
    headers, me = await _me(db_session, customer_headers)
    number = (await delivered_order(db_session, user=me)).number
    h = {**headers, **_key()}
    for _ in range(2):
        r = await integration_client.post(f"{BASE}/market/{number}/snooze", headers=h)
        assert r.status_code == 204
    assert len(list((await db_session.scalars(select(ReviewPrompt))).all())) == 1


async def test_signed_out_is_401(integration_client: AsyncClient) -> None:
    assert (await integration_client.get(f"{BASE}/pending")).status_code == 401
    r = await integration_client.put(
        f"{BASE}/market/ABCDEFGH", json={"rating": 5, "locale": "ru"}, headers=_key()
    )
    assert r.status_code == 401


async def test_the_pending_deal_carries_its_rarity_color(
    db_session: AsyncSession, integration_client: AsyncClient, customer_headers: Headers
) -> None:
    """The prompt lights the skin by its rarity: an order's item, a sale's top item by name."""
    headers, me = await _me(db_session, customer_headers)
    order = await delivered_order(db_session, user=me, days_ago=2)
    item = await db_session.get(SkinItem, order.skin_item_id)
    assert item is not None
    item.rarity_color = "#eb4b4b"
    await db_session.commit()
    deal = (await integration_client.get(f"{BASE}/pending", headers=headers)).json()["deal"]
    assert deal["rarity_color"] == "#eb4b4b"

    sale = await credited_sale(db_session, user=me, days_ago=1)
    top = await db_session.scalar(
        select(SaleItem.name)
        .where(SaleItem.sale_id == sale.id)
        .order_by(SaleItem.price_uzs.desc(), SaleItem.asset_id)
        .limit(1)
    )
    db_session.add(
        SkinItem(
            id=str(uuid4()),
            market_hash_name=str(top),
            phase="",
            slug=f"sold-{uuid4().hex[:6]}",
            category="knives",
            search_text="sold",
            rarity_color="#8847ff",
        )
    )
    await db_session.commit()
    deal = (await integration_client.get(f"{BASE}/pending", headers=headers)).json()["deal"]
    assert (deal["kind"], deal["rarity_color"]) == ("sale", "#8847ff")
