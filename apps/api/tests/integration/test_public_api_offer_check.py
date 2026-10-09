"""``GET /public/catalog/{item_id}/offers/{offer_id}``: a partner asks, before taking its
buyer's money, whether an offer is still for sale and at what price (ADR-0017, 2026-10-10).
A LIS-SKINS lot is asked live (one ``check-availability``, the API's own budget share); a
Skinslink offer answers from the mirror; a lot gone from the snapshot is ``gone`` with no call."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from csmarket.core import config as cfg
from csmarket.core.redis import get_redis
from csmarket.modules.lisskins.api import (
    Availability,
    LisskinsUnavailableError,
    availability_client,
)
from csmarket.modules.lisskins.availability import BREAKER_KEY
from csmarket.modules.lisskins.models import LisskinsOffer, LisskinsState
from csmarket.modules.public_api import keys
from csmarket.modules.public_api.offers import api_offers, seal_offer_id
from csmarket.modules.skins.models import SkinItem
from csmarket.modules.skinslink.models import SkinslinkItem, SkinslinkState
from csmarket.modules.users.models import User
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.conftest import CUSTOMER_STEAM_ID
from tests.integration.fake_lisskins_client import FakeAvailability
from tests.integration.orders_factory import make_item_and_rate

pytestmark = pytest.mark.asyncio

Headers = Callable[[], Awaitable[dict[str, str]]]
Live = Callable[[Availability | Exception], FakeAvailability]
LOT = 553_846_266


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for name, value in {
        "SKINSLINK_ENABLED": "true",
        "SKINSLINK_API_KEY": "k",
        "SKINSLINK_SECRET": "s",
        "LISSKINS_ENABLED": "true",
        "LISSKINS_API_KEY": "k",
    }.items():
        monkeypatch.setenv(f"CSMARKET_{name}", value)
    cfg.get_settings.cache_clear()
    yield
    cfg.get_settings.cache_clear()


@pytest.fixture
def live(integration_app: FastAPI) -> Iterator[Live]:
    def use(answer: Availability | Exception) -> FakeAvailability:
        fake = FakeAvailability(answer)
        integration_app.dependency_overrides[availability_client] = lambda: fake
        return fake

    yield use
    integration_app.dependency_overrides.pop(availability_client, None)


async def _item(db: AsyncSession, *, mirror_age: int = 0, snapshot_age: int = 0) -> SkinItem:
    item, _ = await make_item_and_rate(db)
    item.active = True
    at = datetime.now(UTC)
    db.add_all(
        [
            LisskinsState(id=1, snapshot_at=at - timedelta(seconds=snapshot_age), lots=1),
            LisskinsOffer(id=LOT, skin_item_id=item.id, price_units=4_000, asset_id="9"),
            SkinslinkState(id=1, cursor="c", mirror_synced_at=at - timedelta(seconds=mirror_age)),
            SkinslinkItem(
                id="380",
                market_hash_name=item.market_hash_name,
                phase="",
                price_units=4_100,
                skin_item_id=item.id,
            ),
        ]
    )
    await db.commit()
    await db.refresh(item)
    return item


async def _token(db: AsyncSession, customer_headers: Headers) -> str:
    await customer_headers()
    user = await db.scalar(select(User).where(User.steam_id == CUSTOMER_STEAM_ID))
    assert user is not None
    key, token = await keys.issue(db, user=user)
    key.pricing_profile = "cost"
    await db.commit()
    return token


async def _ids(db: AsyncSession, item: SkinItem) -> dict[str, str]:
    priced = await api_offers(
        db, item, profile="cost", settings=cfg.get_settings(), now=datetime.now(UTC)
    )
    return {p.offer.source: p.public_id for p in priced}


def _url(item: SkinItem, offer_id: str) -> str:
    return f"/api/v1/public/catalog/{item.id}/offers/{offer_id}"


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_a_skinslink_offer_answers_from_the_mirror(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession, live: Live
) -> None:
    item = await _item(db_session)
    token = await _token(db_session, customer_headers)
    fake = live(Availability(available={}, unavailable=frozenset({LOT})))
    offer = (await _ids(db_session, item))["skinslink"]
    r = await integration_client.get(_url(item, offer), headers=_h(token))
    assert r.status_code == 200, r.text
    assert r.json() == {
        "offer_id": offer,
        "status": "available",
        "price_usd": "4.100",
        "retail_price_usd": r.json()["retail_price_usd"],
    }
    assert fake.calls == []


async def test_a_lisskins_lot_is_asked_live(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession, live: Live
) -> None:
    item = await _item(db_session)
    token = await _token(db_session, customer_headers)
    fake = live(Availability(available={LOT: Decimal("4")}, unavailable=frozenset()))
    offer = (await _ids(db_session, item))["lisskins"]
    r = await integration_client.get(_url(item, offer), headers=_h(token))
    assert r.status_code == 200, r.text
    assert (r.json()["status"], r.json()["price_usd"]) == ("available", "4.000")
    assert fake.calls == [[LOT]]


async def test_a_sold_lot_is_gone(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession, live: Live
) -> None:
    item = await _item(db_session)
    token = await _token(db_session, customer_headers)
    live(Availability(available={}, unavailable=frozenset({LOT})))
    offer = (await _ids(db_session, item))["lisskins"]
    r = await integration_client.get(_url(item, offer), headers=_h(token))
    assert r.status_code == 200, r.text
    assert r.json() == {"offer_id": offer, "status": "gone", "price_usd": None}


async def test_a_moved_price_is_re_quoted(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession, live: Live
) -> None:
    item = await _item(db_session)
    token = await _token(db_session, customer_headers)
    live(Availability(available={LOT: Decimal("4.5")}, unavailable=frozenset()))
    offer = (await _ids(db_session, item))["lisskins"]
    r = await integration_client.get(_url(item, offer), headers=_h(token))
    assert (r.json()["status"], r.json()["price_usd"]) == ("available", "4.500")


async def test_no_answer_is_unconfirmed_at_the_snapshot_price(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession, live: Live
) -> None:
    item = await _item(db_session)
    token = await _token(db_session, customer_headers)
    live(LisskinsUnavailableError("down"))
    offer = (await _ids(db_session, item))["lisskins"]
    try:
        r = await integration_client.get(_url(item, offer), headers=_h(token))
        assert (r.json()["status"], r.json()["price_usd"]) == ("unconfirmed", "4.000")
    finally:
        await get_redis().delete(BREAKER_KEY)


async def test_a_lot_gone_from_the_snapshot_is_gone_without_a_call(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession, live: Live
) -> None:
    item = await _item(db_session)
    token = await _token(db_session, customer_headers)
    fake = live(Availability(available={LOT: Decimal("4")}, unavailable=frozenset()))
    offer = (await _ids(db_session, item))["lisskins"]
    await db_session.execute(delete(LisskinsOffer).where(LisskinsOffer.id == LOT))
    await db_session.commit()
    r = await integration_client.get(_url(item, offer), headers=_h(token))
    assert r.json()["status"] == "gone"
    assert fake.calls == []


async def test_a_forged_or_foreign_offer_id_is_404(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession, live: Live
) -> None:
    item = await _item(db_session)
    token = await _token(db_session, customer_headers)
    live(Availability(available={}, unavailable=frozenset()))
    for bad in ("not-a-token", seal_offer_id("another-item", f"ls:{LOT}")):
        r = await integration_client.get(_url(item, bad), headers=_h(token))
        assert r.status_code == 404, r.text
        assert r.json()["code"] == "offer_not_found"
    r = await integration_client.get(_url(item, "x").replace(item.id, "nope"), headers=_h(token))
    assert (r.status_code, r.json()["code"]) == (404, "item_not_found")


async def test_a_skinslink_offer_from_a_lagging_mirror_is_unconfirmed(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession, live: Live
) -> None:
    item = await _item(db_session, mirror_age=60)
    token = await _token(db_session, customer_headers)
    live(Availability(available={}, unavailable=frozenset()))
    offer = (await _ids(db_session, item))["skinslink"]
    r = await integration_client.get(_url(item, offer), headers=_h(token))
    assert (r.json()["status"], r.json()["price_usd"]) == ("unconfirmed", "4.100")


async def test_a_stale_source_is_unconfirmed_never_gone(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession, live: Live
) -> None:
    item = await _item(db_session)
    token = await _token(db_session, customer_headers)
    fake = live(Availability(available={LOT: Decimal("4")}, unavailable=frozenset()))
    ids = await _ids(db_session, item)
    # Both sources go stale after the partner read the offers: their lots drop from our lists.
    await db_session.execute(
        update(SkinslinkState).values(mirror_synced_at=datetime.now(UTC) - timedelta(hours=1))
    )
    await db_session.execute(
        update(LisskinsState).values(snapshot_at=datetime.now(UTC) - timedelta(hours=1))
    )
    await db_session.commit()
    for offer in ids.values():
        r = await integration_client.get(_url(item, offer), headers=_h(token))
        assert r.json() == {"offer_id": offer, "status": "unconfirmed", "price_usd": None}
    assert fake.calls == []


async def test_a_skinslink_offer_gone_from_a_fresh_mirror_is_gone(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession, live: Live
) -> None:
    item = await _item(db_session)
    token = await _token(db_session, customer_headers)
    live(Availability(available={}, unavailable=frozenset()))
    offer = (await _ids(db_session, item))["skinslink"]
    await db_session.execute(delete(SkinslinkItem).where(SkinslinkItem.id == "380"))
    await db_session.commit()
    r = await integration_client.get(_url(item, offer), headers=_h(token))
    assert r.json()["status"] == "gone"
