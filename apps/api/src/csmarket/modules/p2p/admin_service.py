"""The admin «P2P» pages: cards, the journal, requests, settings and the manual credit
(spec 2026-10-19-p2p-topup). Writes flush; the routes audit, remember and commit."""

from __future__ import annotations

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.cursor import decode_cursor, encode_cursor
from csmarket.core.errors import ConflictError, NotFoundError, ValidationError
from csmarket.modules.p2p.card_choice import held_today
from csmarket.modules.p2p.cards import masked, normalize_pan, seal_pan
from csmarket.modules.p2p.models import P2PCard, P2PIncoming, P2PReservation
from csmarket.modules.p2p.schemas import (
    CardIn,
    CardOut,
    CardPatch,
    IncomingOut,
    IncomingPage,
    RequestOut,
    RequestsPage,
    RequestUser,
    SettingsIn,
    SettingsOut,
)
from csmarket.modules.p2p.settings import load_settings
from csmarket.modules.payments.api import credit_received_transfer
from csmarket.modules.users.api import User

_PAGE = 50


async def card_out(db: AsyncSession, card: P2PCard) -> CardOut:
    """A card, masked, with today's received sum."""
    return CardOut(
        id=card.id,
        label=card.label,
        masked=masked(card.pan_last4),
        holder_name=card.holder_name,
        network=card.network,  # type: ignore[arg-type]  # the table's check
        active=card.active,
        min_amount_uzs=str(card.min_amount_uzs),
        max_amount_uzs=str(card.max_amount_uzs),
        daily_limit_uzs=None if card.daily_limit_uzs is None else str(card.daily_limit_uzs),
        today_uzs=str(await held_today(db, card, now())),
        created_at=card.created_at,
    )


async def list_cards(db: AsyncSession) -> list[CardOut]:
    """Every card, newest first."""
    cards = (await db.execute(select(P2PCard).order_by(P2PCard.created_at.desc()))).scalars()
    return [await card_out(db, c) for c in cards]


def _bounds(lo: int, hi: int, daily: int | None) -> None:
    if hi < lo or (daily is not None and daily < hi):
        raise ValidationError(
            "min ≤ max ≤ daily limit", code="p2p_card_bounds", min=lo, max=hi, daily=daily
        )


async def add_card(db: AsyncSession, body: CardIn, *, admin_id: str) -> P2PCard:
    """Seal and add a card.

    Raises:
        ValidationError: ``p2p_pan_invalid``, ``p2p_card_bounds``.
        ConflictError: ``p2p_last4_taken`` — another card of ours ends in the same four digits.
    """
    pan = normalize_pan(body.pan)
    _bounds(body.min_amount_uzs, body.max_amount_uzs, body.daily_limit_uzs)
    if await db.scalar(select(P2PCard.id).where(P2PCard.pan_last4 == pan[-4:])):
        raise ConflictError("a card with these last four digits exists", code="p2p_last4_taken")
    ciphertext, nonce = seal_pan(pan)
    card = P2PCard(
        label=body.label,
        pan_ciphertext=ciphertext,
        pan_nonce=nonce,
        pan_last4=pan[-4:],
        holder_name=body.holder_name,
        network=body.network,
        min_amount_uzs=body.min_amount_uzs,
        max_amount_uzs=body.max_amount_uzs,
        daily_limit_uzs=body.daily_limit_uzs,
        updated_by=admin_id,
    )
    db.add(card)
    await db.flush()
    await db.refresh(card)
    return card


async def patch_card(db: AsyncSession, card_id: str, body: CardPatch, *, admin_id: str) -> P2PCard:
    """Change a card's switch, label or limits.

    Raises:
        NotFoundError: no such card. ValidationError: ``p2p_card_bounds``.
    """
    card = await db.get(P2PCard, card_id, with_for_update=True)
    if card is None:
        raise NotFoundError("card not found", code="p2p_card_not_found")
    if body.active is not None:
        card.active = body.active
    if body.label is not None:
        card.label = body.label
    if body.min_amount_uzs is not None:
        card.min_amount_uzs = body.min_amount_uzs
    if body.max_amount_uzs is not None:
        card.max_amount_uzs = body.max_amount_uzs
    if body.no_daily_limit:
        card.daily_limit_uzs = None
    elif body.daily_limit_uzs is not None:
        card.daily_limit_uzs = body.daily_limit_uzs
    _bounds(card.min_amount_uzs, card.max_amount_uzs, card.daily_limit_uzs)
    card.updated_by, card.updated_at = admin_id, now()
    await db.flush()
    return card


async def _blocking_request(db: AsyncSession, row: P2PIncoming) -> bool:
    """A request of this card and amount is still pending or quarantined: crediting now could
    pay one transfer twice."""
    if row.amount_uzs is None or row.card_last4 is None:
        return False
    found = await db.scalar(
        select(P2PReservation.id)
        .join(P2PCard, P2PCard.id == P2PReservation.card_id)
        .where(
            P2PCard.pan_last4 == row.card_last4,
            P2PReservation.amount_uzs == int(row.amount_uzs),
            P2PReservation.holds_amount.is_(True),
            P2PReservation.status != "paid",
        )
    )
    return found is not None


def _creditable(row: P2PIncoming) -> bool:
    return (
        row.kind == "credit"
        and row.result == "unmatched"
        and row.credited_user_id is None
        and row.amount_uzs is not None
        and row.amount_uzs == row.amount_uzs.to_integral_value()
    )


def incoming_out(row: P2PIncoming, number: str | None) -> IncomingOut:
    """A journal row as the admin sees it."""
    return IncomingOut(
        id=row.id,
        kind=row.kind,  # type: ignore[arg-type]  # the table's check
        amount_uzs=None if row.amount_uzs is None else f"{row.amount_uzs:f}",
        card_last4=row.card_last4,
        source_text=row.source_text,
        bank_time=row.bank_time,
        balance_after=None if row.balance_after is None else f"{row.balance_after:f}",
        chain_ok=row.chain_ok,
        result=row.result,  # type: ignore[arg-type]  # the table's check
        number=number,
        received_at=row.received_at,
        can_credit=_creditable(row),
    )


async def journal(
    db: AsyncSession, *, amount: int | None, result: str | None, cursor: str | None
) -> IncomingPage:
    """The journal newest first; ``amount`` = whole soʻm, ``result`` one of the three."""
    stmt = (
        select(P2PIncoming, P2PReservation.number)
        .outerjoin(P2PReservation, P2PReservation.id == P2PIncoming.reservation_id)
        .order_by(P2PIncoming.received_at.desc(), P2PIncoming.id.desc())
        .limit(_PAGE + 1)
    )
    if amount is not None:
        stmt = stmt.where(P2PIncoming.amount_uzs == amount)
    if result is not None:
        stmt = stmt.where(P2PIncoming.result == result)
    if cursor is not None:
        at, last_id = decode_cursor(cursor)
        stmt = stmt.where(
            or_(
                P2PIncoming.received_at < at,
                and_(P2PIncoming.received_at == at, P2PIncoming.id < last_id),
            )
        )
    rows = list((await db.execute(stmt)).all())
    page = rows[:_PAGE]
    nxt = encode_cursor(page[-1][0].received_at, page[-1][0].id) if len(rows) > _PAGE else None
    return IncomingPage(items=[incoming_out(r, n) for r, n in page], next_cursor=nxt)


async def requests(db: AsyncSession, *, status: str | None, cursor: str | None) -> RequestsPage:
    """Requests newest first, with the buyer and the masked card."""
    stmt = (
        select(P2PReservation, P2PCard.pan_last4, User.display_name, User.avatar_url)
        .join(P2PCard, P2PCard.id == P2PReservation.card_id)
        .join(User, User.id == P2PReservation.user_id)
        .order_by(P2PReservation.created_at.desc(), P2PReservation.id.desc())
        .limit(_PAGE + 1)
    )
    if status is not None:
        stmt = stmt.where(P2PReservation.status == status)
    if cursor is not None:
        at, last_id = decode_cursor(cursor)
        stmt = stmt.where(
            or_(
                P2PReservation.created_at < at,
                and_(P2PReservation.created_at == at, P2PReservation.id < last_id),
            )
        )
    rows = list((await db.execute(stmt)).all())
    page = rows[:_PAGE]
    nxt = encode_cursor(page[-1][0].created_at, page[-1][0].id) if len(rows) > _PAGE else None
    return RequestsPage(
        items=[
            RequestOut(
                number=r.number,
                status=r.status,  # type: ignore[arg-type]  # the table's check
                amount_uzs=str(r.amount_uzs),
                card_masked=masked(last4),
                user=RequestUser(id=r.user_id, display_name=name, avatar_url=avatar),
                created_at=r.created_at,
                expires_at=r.expires_at,
                closed_at=r.closed_at,
            )
            for r, last4, name, avatar in page
        ],
        next_cursor=nxt,
    )


async def settings_out(db: AsyncSession) -> SettingsOut:
    """The settings row and the connection's state."""
    s = await load_settings(db)
    return SettingsOut(
        humo_bot_user_id=s.humo_bot_user_id,
        owner_telegram_user_id=s.owner_telegram_user_id,
        min_amount_uzs=s.min_amount_uzs,
        max_amount_uzs=s.max_amount_uzs,
        daily_count=s.daily_count,
        daily_amount_uzs=s.daily_amount_uzs,
        connected=bool(s.business_connection_id),
        last_received_at=s.last_received_at,
        updated_at=s.updated_at,
    )


async def save_settings(db: AsyncSession, body: SettingsIn, *, admin_id: str) -> None:
    """Replace the editable fields. Raises ``ValidationError`` ``p2p_limits``."""
    if not (body.min_amount_uzs <= body.max_amount_uzs <= body.daily_amount_uzs):
        raise ValidationError("min ≤ max ≤ the daily sum", code="p2p_limits")
    s = await load_settings(db, lock=True)
    s.humo_bot_user_id = body.humo_bot_user_id
    s.owner_telegram_user_id = body.owner_telegram_user_id
    s.min_amount_uzs, s.max_amount_uzs = body.min_amount_uzs, body.max_amount_uzs
    s.daily_count, s.daily_amount_uzs = body.daily_count, body.daily_amount_uzs
    s.updated_by, s.updated_at = admin_id, now()
    await db.flush()


async def credit_by_hand(
    db: AsyncSession, incoming_id: str, *, user_id: str
) -> tuple[P2PIncoming, str]:
    """Book an unmatched transfer for ``user_id``: a new top-up settled at once.

    Raises:
        NotFoundError: no such row, or no such user.
        ConflictError: ``p2p_already_credited``, ``p2p_not_creditable`` (not an unmatched
            whole-soʻm credit), ``p2p_quarantine`` (a request of that card and amount still
            holds it — wait it out).
    """
    row = await db.get(P2PIncoming, incoming_id, with_for_update=True)
    if row is None:
        raise NotFoundError("notification not found", code="p2p_incoming_not_found")
    if row.credited_user_id is not None or row.result == "matched":
        raise ConflictError("this transfer is already booked", code="p2p_already_credited")
    if not _creditable(row) or row.amount_uzs is None:
        raise ConflictError("only an unmatched credit can be booked", code="p2p_not_creditable")
    if await _blocking_request(db, row):
        raise ConflictError("a request still holds this amount", code="p2p_quarantine")
    if await db.get(User, user_id) is None:
        raise NotFoundError("user not found", code="user_not_found")
    topup = await credit_received_transfer(
        db,
        user_id=user_id,
        amount_uzs=row.amount_uzs,
        provider="p2p",
        event_id=f"p2p-manual:{row.id}",
    )
    row.result, row.credited_user_id = "matched", user_id
    await db.flush()
    return row, topup.number


__all__ = [
    "add_card",
    "card_out",
    "credit_by_hand",
    "incoming_out",
    "journal",
    "list_cards",
    "patch_card",
    "requests",
    "save_settings",
    "settings_out",
]
