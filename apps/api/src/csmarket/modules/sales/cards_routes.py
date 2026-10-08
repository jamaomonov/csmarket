"""``/api/v1/payout-cards`` — the signed-in user's saved payout cards (spec 2026-10-08 §5).

A card is added only with a sale (``POST /sell`` with ``new_card``); here it is listed and
forgotten. Routers parse and dispatch; the logic is :mod:`.cards`.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Response
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.api.v1.deps import db_session
from csmarket.core.idempotency import IDEMPOTENCY_HEADER, require_idempotency_key
from csmarket.modules.auth.api import current_user
from csmarket.modules.sales.cards import delete_card, live_cards
from csmarket.modules.sales.schemas import CardOut, CardsOut
from csmarket.modules.users.api import User

router = APIRouter(prefix="/payout-cards", tags=["sales"])

Db = Annotated[AsyncSession, Depends(db_session)]
Me = Annotated[User, Depends(current_user)]


@router.get("", response_model=CardsOut, summary="My payout cards")
async def get_cards(user: Me, db: Db) -> CardsOut:
    """Live cards, oldest first: type and last four digits."""
    return CardsOut(items=[CardOut.of(c) for c in await live_cards(db, user.id)])


@router.delete(
    "/{card_id}",
    status_code=204,
    responses={404: {"description": "Not my card"}},
    summary="Forget a payout card",
)
async def remove_card(
    card_id: uuid.UUID,
    user: Me,
    db: Db,
    idempotency_key: Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)] = None,
) -> Response:
    """Soft delete; the key is required but nothing is stored for it.

    A repeat is a no-op 204, so no replay is persisted (the AGENTS §10 exception).
    """
    require_idempotency_key(idempotency_key)
    await delete_card(db, user_id=user.id, card_id=str(card_id))
    await db.commit()
    return Response(status_code=204)


__all__ = ["router"]
