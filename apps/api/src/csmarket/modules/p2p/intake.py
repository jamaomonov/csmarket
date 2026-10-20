"""File a @HUMOcardbot notification and, if it pays a request, settle the top-up
(spec 2026-10-19-p2p-topup).

One transaction, owned by the caller: the journal row, the request's ``paid`` and the
top-up's credit (``payments.settle``) commit together or not at all. Alerts are returned as
kinds and counted by the caller after commit (Prometheus → Alertmanager).

The bot's feed is shared with another project through a relay: a credit to a card that is
not ours (no card of ours, active or not, ends in its last4) is journaled ``ignored`` and
never matched.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.logging import get_logger
from csmarket.modules.p2p.integrity import violated_constraint
from csmarket.modules.p2p.models import P2PCard, P2PIncoming, P2PReservation, P2PSettings
from csmarket.modules.p2p.parsing import ParsedNotification, parse_humo
from csmarket.modules.p2p.reservations import QUARANTINE
from csmarket.modules.p2p.settings import load_settings
from csmarket.modules.payments.api import (
    AlreadyPaidError,
    InvalidTransitionError,
    Payment,
    settle,
)

log = get_logger("csmarket.p2p.intake")

Status = Literal["dropped", "duplicate", "matched", "unmatched", "ignored"]
Alert = Literal["unparsed", "chain_break", "ambiguous_card", "settle_refused"]
_MESSAGE_KEY = "uq_p2p_incoming_message"


@dataclass
class IntakeResult:
    """What one update turned into: ``dropped`` (not from the HUMO bot), ``duplicate``
    (already journaled), ``matched`` (settled a request), ``unmatched`` (a credit nobody was
    waiting for) or ``ignored`` (a debit, unparsed, or a card that is not ours)."""

    status: Status
    number: str | None = None
    alerts: list[Alert] = field(default_factory=list)


def _humo_message(update: dict[str, Any], settings: P2PSettings) -> dict[str, Any] | None:
    """The business message only if it came from the HUMO bot, unforwarded, through the
    owner's pinned connection (anyone with Premium can connect the bot to *their* account
    and feed it look-alikes). Nothing pinned, or no HUMO id, drops everything."""
    msg = update.get("business_message")
    humo_id = settings.humo_bot_user_id
    pinned = settings.business_connection_id
    if not isinstance(msg, dict) or humo_id is None or not pinned:
        return None
    if msg.get("business_connection_id") != pinned:
        return None
    sender = (msg.get("from") or {}).get("id")
    chat = (msg.get("chat") or {}).get("id")
    if sender != humo_id or chat != humo_id or msg.get("forward_origin"):
        return None
    return msg


def _track_connection(settings: P2PSettings, connection: dict[str, Any]) -> None:
    """Pin the owner's Business connection on enable; unpin it on disable. Logs health only —
    never the user id, never a name."""
    user_id = (connection.get("user") or {}).get("id")
    conn_id = connection.get("id")
    enabled = connection.get("is_enabled") is True
    owner = settings.owner_telegram_user_id
    is_owner = owner is not None and user_id == owner
    if is_owner and enabled and isinstance(conn_id, str) and conn_id:
        settings.business_connection_id = conn_id
        settings.connection_enabled = True
    elif not enabled and conn_id is not None and conn_id == settings.business_connection_id:
        settings.business_connection_id = None
        settings.connection_enabled = False
    log.info("p2p.business_connection", is_enabled=connection.get("is_enabled"), owner=is_owner)


async def _chain_ok(
    db: AsyncSession, p: ParsedNotification, connection_id: str, message_id: int
) -> bool | None:
    """Whether the previous balance plus this movement equals this balance (the same card's
    row with the greatest Telegram message id below this one); ``None`` when not judged."""
    if p.kind not in ("credit", "debit") or p.balance_after is None or p.amount is None:
        return None
    prev = await db.scalar(
        select(P2PIncoming)
        .where(
            P2PIncoming.card_last4 == p.card_last4,
            P2PIncoming.business_connection_id == connection_id,
            P2PIncoming.telegram_message_id < message_id,
            P2PIncoming.balance_after.is_not(None),
        )
        .order_by(P2PIncoming.telegram_message_id.desc())
        .limit(1)
    )
    if prev is None or prev.balance_after is None:
        return None
    signed = p.amount if p.kind == "credit" else -p.amount
    return prev.balance_after + signed == p.balance_after


async def _payable(
    db: AsyncSession, p: ParsedNotification, received_at: datetime
) -> P2PReservation | None:
    """Lock the request this credit pays, if one is waiting. An ``expired`` row whose
    quarantine still holds the amount is accepted (a late delivery of an on-time transfer);
    ``expires_at >= paid_at`` keeps genuinely late transfers out. Bank time has minute
    precision. An amount with tiyin never matches."""
    if p.kind != "credit" or p.amount is None or p.amount != p.amount.to_integral_value():
        return None
    paid_at = p.bank_time or received_at
    found: P2PReservation | None = await db.scalar(
        select(P2PReservation)
        .join(P2PCard, P2PCard.id == P2PReservation.card_id)
        .where(
            # Not ``P2PCard.active``: the buyer saw the number; a card switched off since
            # must not strand an on-time transfer (the switch only stops new requests).
            P2PCard.pan_last4 == p.card_last4,
            P2PReservation.amount_uzs == int(p.amount),
            P2PReservation.status.in_(("pending", "expired")),
            P2PReservation.holds_amount.is_(True),
            P2PReservation.created_at < paid_at + timedelta(minutes=1),
            P2PReservation.expires_at >= paid_at,
        )
        .order_by(P2PReservation.created_at)
        .limit(1)
        .with_for_update(of=P2PReservation)
    )
    return found


async def _cards_ending(db: AsyncSession, last4: str | None, *, active_only: bool) -> int:
    stmt = select(func.count()).select_from(P2PCard).where(P2PCard.pan_last4 == last4)
    if active_only:
        stmt = stmt.where(P2PCard.active.is_(True))
    return int(await db.scalar(stmt) or 0)


async def _credit(
    db: AsyncSession,
    row: P2PIncoming,
    parsed: ParsedNotification,
    received_at: datetime,
    result: IntakeResult,
) -> None:
    """Match a credit to a request and settle its top-up, or mark it unmatched."""
    if await _cards_ending(db, parsed.card_last4, active_only=True) > 1:
        row.result, result.status = "unmatched", "unmatched"
        result.alerts.append("ambiguous_card")
        return
    request = await _payable(db, parsed, received_at)
    payment = await db.get(Payment, request.payment_id) if request is not None else None
    if request is None or payment is None:
        row.result, result.status = "unmatched", "unmatched"
        log.info("p2p.unmatched", amount=str(parsed.amount), card_last4=parsed.card_last4)
        return
    try:
        async with db.begin_nested():
            await settle(db, payment=payment, event_id=f"p2p:{row.id}")
    except (AlreadyPaidError, InvalidTransitionError):
        # The top-up was settled another way meanwhile: keep the transfer on the journal as
        # money to resolve by hand, never lose it in a rollback.
        row.result, result.status = "unmatched", "unmatched"
        result.alerts.append("settle_refused")
        log.warning("p2p.settle_refused", number=request.number)
        return
    # The amount stays held for the quarantine: a payer's accidental second transfer must land
    # unmatched, not pay whoever asks for the same sum next.
    request.status = "paid"
    request.closed_at = received_at
    request.quarantine_until = received_at + QUARANTINE
    request.incoming_id = row.id
    row.result, row.reservation_id = "matched", request.id
    result.status, result.number = "matched", request.number
    log.info("p2p.matched", number=request.number, amount_uzs=request.amount_uzs)


async def ingest_update(
    db: AsyncSession, update: dict[str, Any], *, received_at: datetime
) -> IntakeResult:
    """Journal one Telegram update and settle the request it pays, if any. The caller
    commits, then counts the alerts."""
    settings = await load_settings(db)
    connection = update.get("business_connection")
    if isinstance(connection, dict):
        _track_connection(settings, connection)
        await db.flush()
        return IntakeResult("dropped")
    msg = _humo_message(update, settings)
    if msg is None:
        return IntakeResult("dropped")
    message_id = msg.get("message_id")
    if not isinstance(message_id, int) or isinstance(message_id, bool):
        log.warning("p2p.malformed_update", field="message_id")
        return IntakeResult("dropped")
    text = str(msg.get("text") or "")
    parsed = parse_humo(text)
    row = P2PIncoming(
        business_connection_id=str(msg.get("business_connection_id") or ""),
        telegram_message_id=message_id,
        kind=parsed.kind,
        amount_uzs=parsed.amount,
        source_text=(parsed.source or "")[:128] or None,
        card_last4=parsed.card_last4,
        bank_time=parsed.bank_time,
        balance_after=parsed.balance_after,
        raw_text=text,
        result="ignored",
        received_at=received_at,
    )
    row.chain_ok = await _chain_ok(db, parsed, row.business_connection_id, message_id)
    try:
        async with db.begin_nested():
            db.add(row)
            await db.flush()
    except IntegrityError as exc:
        if violated_constraint(exc, (_MESSAGE_KEY,)) is None:
            raise
        return IntakeResult("duplicate")
    settings.last_received_at = received_at
    result = IntakeResult("ignored")
    if parsed.card_last4 is not None and not await _cards_ending(
        db, parsed.card_last4, active_only=False
    ):
        log.info("p2p.foreign_card", kind=parsed.kind)
        await db.flush()
        return result
    if parsed.kind == "unparsed":
        result.alerts.append("unparsed")
    if row.chain_ok is False:
        result.alerts.append("chain_break")
    if parsed.kind == "credit":
        await _credit(db, row, parsed, received_at, result)
    await db.flush()
    return result


__all__ = ["Alert", "IntakeResult", "ingest_update"]
