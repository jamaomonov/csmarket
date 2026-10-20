"""``/api/v1/admin/p2p/*`` — the admin «P2P» pages (spec 2026-10-19-p2p-topup).

Admin only. Every write requires an ``Idempotency-Key``: replay lookup → the change → audit →
replay row → commit; the same key on another body is 409 ``idempotency_mismatch``. A card's
full number is never stored in a replay row or an audit payload (only its last four).
"""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.api.v1.deps import db_session
from csmarket.modules.admin.api import record, remember, replayed, require_admin, required_key
from csmarket.modules.p2p import admin_service as svc
from csmarket.modules.p2p.cards import normalize_pan
from csmarket.modules.p2p.schemas import (
    CardIn,
    CardOut,
    CardPatch,
    CardsOut,
    CreditIn,
    CreditOut,
    IncomingPage,
    RequestsPage,
    SettingsIn,
    SettingsOut,
)
from csmarket.modules.users.api import User

router = APIRouter(prefix="/admin/p2p", tags=["admin"], dependencies=[Depends(require_admin)])

Db = Annotated[AsyncSession, Depends(db_session, scope="function")]
Admin = Annotated[User, Depends(require_admin)]
Key = Annotated[str, Depends(required_key)]


@router.get("/cards", response_model=CardsOut, summary="P2P cards")
async def get_cards(db: Db) -> CardsOut:
    """Every card, masked, newest first, with today's received sum."""
    return CardsOut(items=await svc.list_cards(db))


@router.post(
    "/cards",
    response_model=CardOut,
    status_code=201,
    responses={409: {"description": "`p2p_last4_taken` or `idempotency_mismatch`"}},
    summary="Add a P2P card",
)
async def post_card(body: CardIn, admin: Admin, db: Db, key: Key) -> CardOut:
    """The full number once; it is sealed and never shown again. Audited ``p2p.card.add``."""
    scope = "admin.p2p.card.add"
    request = {**body.model_dump(exclude={"pan"}), "last4": normalize_pan(body.pan)[-4:]}
    if (hit := await replayed(db, scope=scope, key=key, request=request)) is not None:
        return CardOut.model_validate(hit)
    card = await svc.add_card(db, body, admin_id=admin.id)
    await record(
        db,
        actor_id=admin.id,
        action="p2p.card.add",
        target_type="p2p_card",
        target_id=card.id,
        payload={"last4": card.pan_last4, "label": card.label},
    )
    out = await svc.card_out(db, card)
    await remember(db, scope=scope, key=key, request=request, response=out.model_dump(mode="json"))
    await db.commit()
    return out


@router.patch("/cards/{card_id}", response_model=CardOut, summary="Change a P2P card")
async def patch_card(
    card_id: uuid.UUID, body: CardPatch, admin: Admin, db: Db, key: Key
) -> CardOut:
    """Switch a card on or off, rename it, change its limits. Audited ``p2p.card.update``."""
    scope = "admin.p2p.card.update"
    request = {"id": str(card_id), **body.model_dump()}
    if (hit := await replayed(db, scope=scope, key=key, request=request)) is not None:
        return CardOut.model_validate(hit)
    card = await svc.patch_card(db, str(card_id), body, admin_id=admin.id)
    await record(
        db,
        actor_id=admin.id,
        action="p2p.card.update",
        target_type="p2p_card",
        target_id=card.id,
        payload={k: str(v) for k, v in body.model_dump(exclude_none=True).items()},
    )
    out = await svc.card_out(db, card)
    await remember(db, scope=scope, key=key, request=request, response=out.model_dump(mode="json"))
    await db.commit()
    return out


@router.get("/incoming", response_model=IncomingPage, summary="P2P journal")
async def get_incoming(
    db: Db,
    amount: Annotated[int | None, Query(ge=1)] = None,
    result: Literal["matched", "unmatched", "ignored"] | None = None,
    cursor: str | None = None,
) -> IncomingPage:
    """Every HUMO notification newest first; ``amount`` is whole soʻm."""
    return await svc.journal(db, amount=amount, result=result, cursor=cursor)


@router.get("/requests", response_model=RequestsPage, summary="P2P requests")
async def get_requests(
    db: Db,
    status: Literal["pending", "paid", "expired", "cancelled"] | None = None,
    cursor: str | None = None,
) -> RequestsPage:
    """Top-up requests newest first, with the buyer and the masked card."""
    return await svc.requests(db, status=status, cursor=cursor)


@router.get("/settings", response_model=SettingsOut, summary="P2P settings")
async def get_settings_view(db: Db) -> SettingsOut:
    """The trusted Telegram ids, the limits, the connection's state."""
    return await svc.settings_out(db)


@router.put("/settings", response_model=SettingsOut, summary="Save the P2P settings")
async def put_settings(body: SettingsIn, admin: Admin, db: Db, key: Key) -> SettingsOut:
    """Replace the editable settings. Audited ``p2p.settings.save``."""
    scope = "admin.p2p.settings.save"
    request = body.model_dump()
    if (hit := await replayed(db, scope=scope, key=key, request=request)) is not None:
        return SettingsOut.model_validate(hit)
    await svc.save_settings(db, body, admin_id=admin.id)
    await record(
        db,
        actor_id=admin.id,
        action="p2p.settings.save",
        target_type="p2p_settings",
        target_id="1",
        payload={k: str(v) for k, v in request.items() if "telegram" not in k and "bot" not in k},
    )
    out = await svc.settings_out(db)
    await remember(db, scope=scope, key=key, request=request, response=out.model_dump(mode="json"))
    await db.commit()
    return out


@router.post(
    "/incoming/{incoming_id}/credit",
    response_model=CreditOut,
    responses={
        409: {
            "description": "`p2p_already_credited`, `p2p_not_creditable`, `p2p_quarantine` or "
            "`idempotency_mismatch`"
        }
    },
    summary="Book an unmatched transfer for a user",
)
async def post_credit(
    incoming_id: uuid.UUID, body: CreditIn, admin: Admin, db: Db, key: Key
) -> CreditOut:
    """«Зачислить пользователю»: a new top-up for the user, settled at once with the
    transfer's amount. Refused while a request of that card and amount still holds it.
    Audited ``p2p.incoming.credit`` (the note too)."""
    scope = "admin.p2p.incoming.credit"
    request = {"id": str(incoming_id), **body.model_dump()}
    if (hit := await replayed(db, scope=scope, key=key, request=request)) is not None:
        return CreditOut.model_validate(hit)
    row, number = await svc.credit_by_hand(db, str(incoming_id), user_id=body.user_id)
    await record(
        db,
        actor_id=admin.id,
        action="p2p.incoming.credit",
        target_type="p2p_incoming",
        target_id=row.id,
        payload={
            "user_id": body.user_id,
            "amount_uzs": str(row.amount_uzs),
            "topup": number,
            "note": body.note,
        },
    )
    out = CreditOut(incoming=svc.incoming_out(row, None), topup_number=number)
    await remember(db, scope=scope, key=key, request=request, response=out.model_dump(mode="json"))
    await db.commit()
    return out


__all__ = ["router"]
