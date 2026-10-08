"""Saved payout cards: at most three, encrypted at rest, listed and logged by the last four."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import pytest
from csmarket.core.errors import ConflictError, NotFoundError
from csmarket.modules.sales.cards import (
    add_card,
    delete_card,
    live_cards,
    owned_card,
    reveal_number,
)
from csmarket.modules.sales.models import PayoutCard
from csmarket.modules.sales.rules import CardType
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from structlog.testing import capture_logs

from tests.integration.conftest import CUSTOMER_STEAM_ID
from tests.integration.payments_factory import make_user
from tests.integration.sales_factory import HUMO, UZCARD, VISA, make_card

pytestmark = pytest.mark.asyncio

Headers = Callable[[], Awaitable[dict[str, str]]]
KEY = {"Idempotency-Key": "test-card-delete-0001"}


async def test_a_card_number_is_stored_encrypted_and_never_logged_or_listed(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    customer_headers: Headers,
) -> None:
    headers = await customer_headers()
    user_id = (await integration_client.get("/api/v1/me", headers=headers)).json()["id"]
    with capture_logs() as logs:
        card = await add_card(db_session, user_id=user_id, card_type="humo", raw_number=HUMO)
        await db_session.commit()
    assert HUMO not in repr(logs)
    assert any(e.get("last4") == "9015" for e in logs)
    raw = (
        await db_session.execute(
            text("SELECT number_enc::text, number_nonce::text FROM payout_cards WHERE id = :id"),
            {"id": card.id},
        )
    ).one()
    assert HUMO not in raw[0]
    assert HUMO.encode().hex() not in raw[0]
    assert reveal_number(card) == HUMO
    r = await integration_client.get("/api/v1/payout-cards", headers=headers)
    assert r.status_code == 200
    assert HUMO not in r.text
    [item] = r.json()["items"]
    assert (item["id"], item["type"], item["last4"]) == (card.id, "humo", "9015")
    assert CUSTOMER_STEAM_ID not in r.text


async def test_a_fourth_live_card_is_cards_limit(db_session: AsyncSession) -> None:
    user_id = (await make_user(db_session)).id  # read now: a rollback expires the row
    cards: tuple[tuple[str, CardType], ...] = (
        (HUMO, "humo"),
        (UZCARD, "uzcard"),
        (VISA, "uzum_visa"),
    )
    for number, kind in cards:
        await add_card(db_session, user_id=user_id, card_type=kind, raw_number=number)
    await db_session.commit()
    with pytest.raises(ConflictError) as caught:
        await add_card(db_session, user_id=user_id, card_type="humo", raw_number=HUMO)
    assert caught.value.extra["code"] == "cards_limit"
    await db_session.rollback()
    first = (await live_cards(db_session, user_id))[0]
    await delete_card(db_session, user_id=user_id, card_id=first.id)
    await add_card(db_session, user_id=user_id, card_type="humo", raw_number=HUMO)
    await db_session.commit()
    assert len(await live_cards(db_session, user_id)) == 3


async def test_another_users_or_a_deleted_card_is_not_found(db_session: AsyncSession) -> None:
    owner, other = await make_user(db_session), await make_user(db_session)
    card = await make_card(db_session, owner)
    with pytest.raises(NotFoundError):
        await owned_card(db_session, user_id=other.id, card_id=card.id)
    await delete_card(db_session, user_id=owner.id, card_id=card.id)
    await delete_card(db_session, user_id=owner.id, card_id=card.id)  # a repeat is a no-op
    await db_session.commit()
    with pytest.raises(NotFoundError):
        await owned_card(db_session, user_id=owner.id, card_id=card.id)
    stored = await db_session.scalar(select(PayoutCard).where(PayoutCard.id == card.id))
    assert stored is not None
    assert stored.deleted_at is not None  # soft: a request may point at it


async def test_delete_route_needs_a_key_and_answers_204(
    db_session: AsyncSession, integration_client: AsyncClient, customer_headers: Headers
) -> None:
    headers = await customer_headers()
    user_id = (await integration_client.get("/api/v1/me", headers=headers)).json()["id"]
    card = await add_card(db_session, user_id=user_id, card_type="humo", raw_number=HUMO)
    await db_session.commit()
    url = f"/api/v1/payout-cards/{card.id}"
    assert (await integration_client.delete(url, headers=headers)).status_code == 422
    for _ in range(2):
        r = await integration_client.delete(url, headers={**headers, **KEY})
        assert r.status_code == 204
    r = await integration_client.get("/api/v1/payout-cards", headers=headers)
    assert r.json()["items"] == []


async def test_someone_elses_card_cannot_be_deleted(
    db_session: AsyncSession, integration_client: AsyncClient, customer_headers: Headers
) -> None:
    headers = await customer_headers()
    card = await make_card(db_session, await make_user(db_session))
    r = await integration_client.delete(
        f"/api/v1/payout-cards/{card.id}", headers={**headers, **KEY}
    )
    assert r.status_code == 404
