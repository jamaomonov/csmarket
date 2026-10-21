"""«На проверке»: the admin's list of held kassa payments and the two decisions (spec
2026-10-21-payment-risk-limits).

:func:`release` («Пропустить») does what ``settle`` would have done without the hold: an order
goes ``paid`` through ``mark_paid`` (``NOTIFY orders``, the worker buys), a top-up goes
``succeeded`` and is credited once, keyed by the top-up. :func:`mark_returned` («Вернул на
карту») records that the admin gave the money back in the kassa: nothing is credited, the
attempt goes ``refunded``, an order ``cancelled`` (its kassa stays in ``paid_with``), a top-up
``rejected``. Both lock in ``hooks``' order (the owner, then the payment), then the hold, and
refuse a hold already decided (``hold_decided``).

Kept apart from ``holds``: this module imports ``admin.api``, whose ``users_service`` imports
``payments.api`` → ``hooks`` → ``holds``; only the router imports this one.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import Row, Select, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from csmarket.core.cursor import decode_cursor, encode_cursor
from csmarket.core.errors import ConflictError, NotFoundError
from csmarket.core.logging import get_logger
from csmarket.core.money import wire_uzs
from csmarket.modules.admin.api import record
from csmarket.modules.orders.api import Order, mark_paid
from csmarket.modules.orders.api import move as move_order
from csmarket.modules.payments.fsm import move as move_payment
from csmarket.modules.payments.holds import close
from csmarket.modules.payments.hooks import lock_owner_then_payment
from csmarket.modules.payments.models import Payment, WalletTopup
from csmarket.modules.realtime.api import nudge
from csmarket.modules.risk.api import HoldDecision, PaymentHold
from csmarket.modules.users.api import User
from csmarket.modules.wallet.api import credit_topup

log = get_logger("csmarket.payments.holds")

#: Holds per page.
PAGE = 50

HoldState = Literal["open", "decided"]


class HoldUserOut(BaseModel):
    """A user as the holds page names them."""

    id: str
    display_name: str | None


class HoldOut(BaseModel):
    """One held payment and its decision (``decision`` ``None`` = open)."""

    id: str
    number: str
    kind: str
    provider: str
    amount_uzs: str
    reason: str
    window_sum_uzs: str | None
    limit_uzs: str | None
    user: HoldUserOut
    created_at: datetime
    decision: str | None
    decided_by: HoldUserOut | None
    decided_at: datetime | None


class HoldPage(BaseModel):
    """A page of holds, newest first; ``next_cursor`` ``None`` on the last page."""

    items: list[HoldOut]
    next_cursor: str | None


def _money(value: Decimal | None) -> str | None:
    return wire_uzs(value) if value is not None else None


def _who(user: User | None) -> HoldUserOut | None:
    return HoldUserOut(id=user.id, display_name=user.display_name) if user is not None else None


def _out(row: PaymentHold, number: str, user: User, admin: User | None) -> HoldOut:
    owner = _who(user)
    assert owner is not None
    return HoldOut(
        id=row.id,
        number=number,
        kind=row.kind,
        provider=row.provider,
        amount_uzs=wire_uzs(row.amount_uzs),
        reason=row.reason,
        window_sum_uzs=_money(row.window_sum_uzs),
        limit_uzs=_money(row.limit_uzs),
        user=owner,
        created_at=row.created_at,
        decision=row.decision,
        decided_by=_who(admin),
        decided_at=row.decided_at,
    )


def _views(rows: Sequence[Row[PaymentHold, str, User, User]]) -> list[HoldOut]:
    """Views of joined rows; the admin column is ``None`` on an open hold (outer join)."""
    return [_out(*row) for row in rows]


def _joined() -> Select[PaymentHold, str, User, User]:
    """Holds with their attempt's number, their user and the deciding admin, in one query."""
    owner, admin = aliased(User), aliased(User)
    return (
        select(PaymentHold, Payment.number, owner, admin)
        .join(Payment, Payment.id == PaymentHold.payment_id)
        .join(owner, owner.id == PaymentHold.user_id)
        .outerjoin(admin, admin.id == PaymentHold.decided_by)
    )


async def list_holds(db: AsyncSession, *, state: HoldState, cursor: str | None) -> HoldPage:
    """Open holds by ``created_at`` or decided ones by ``decided_at``, newest first (keyset).

    Args:
        db: Session.
        state: ``open`` (undecided) or ``decided``.
        cursor: The previous page's ``next_cursor``.

    Returns:
        Up to :data:`PAGE` holds and the cursor of the next page.

    Raises:
        ValidationError: ``cursor`` is not one this list issued (``code="cursor"``).
    """
    is_open = state == "open"
    at = PaymentHold.created_at if is_open else PaymentHold.decided_at
    q = _joined().where(
        PaymentHold.decision.is_(None) if is_open else PaymentHold.decision.is_not(None)
    )
    if cursor is not None:
        c_at, c_id = decode_cursor(cursor)
        q = q.where((at < c_at) | ((at == c_at) & (PaymentHold.id < c_id)))
    rows = list(
        (await db.execute(q.order_by(at.desc(), PaymentHold.id.desc()).limit(PAGE + 1))).all()
    )
    page = rows[:PAGE]
    nxt = None
    if len(rows) > PAGE:
        last = page[-1][0]
        stamp = last.created_at if is_open else last.decided_at
        assert stamp is not None
        nxt = encode_cursor(stamp, last.id)
    return HoldPage(items=_views(page), next_cursor=nxt)


async def _view(db: AsyncSession, hold_id: str) -> HoldOut:
    return _views((await db.execute(_joined().where(PaymentHold.id == hold_id))).all())[0]


async def _decidable(
    db: AsyncSession, hold_id: str
) -> tuple[PaymentHold, Payment, WalletTopup | Order]:
    """Lock the owner, the payment and the hold (``hooks``' lock order), or refuse.

    Raises:
        NotFoundError: no such hold, or ``hold_id`` is not a UUID (``hold_not_found``).
        ConflictError: the hold was already decided (``hold_decided``).
    """
    try:
        uuid.UUID(hold_id)
    except ValueError as exc:
        raise NotFoundError("no such hold", code="hold_not_found") from exc
    row = await db.get(PaymentHold, hold_id)
    if row is None:
        raise NotFoundError("no such hold", code="hold_not_found")
    payment = await db.get_one(Payment, row.payment_id)
    owner = await lock_owner_then_payment(db, payment)
    await db.refresh(row, with_for_update=True)
    if row.decision is not None:
        raise ConflictError("the hold was already decided", code="hold_decided")
    return row, payment, owner


async def _finish(
    db: AsyncSession, *, row: PaymentHold, payment: Payment, decision: HoldDecision, admin_id: str
) -> HoldOut:
    """Close the hold, audit it, log it and answer its view."""
    close(row, decision=decision, admin_id=admin_id)
    action, event = (
        ("payments.hold.release", "payments.hold.released")
        if decision == "released"
        else ("payments.hold.returned", "payments.hold.returned")
    )
    await record(
        db,
        actor_id=admin_id,
        action=action,
        target_type="payment_hold",
        target_id=row.id,
        payload={
            "number": payment.number,
            "provider": row.provider,
            "amount_uzs": wire_uzs(row.amount_uzs),
        },
    )
    await db.flush()
    log.info(
        event,
        number=payment.number,
        provider=row.provider,
        amount=str(row.amount_uzs),
    )
    return await _view(db, row.id)


async def release(db: AsyncSession, *, hold_id: str, admin_id: str) -> HoldOut:
    """«Пропустить»: pay the order (the worker buys) or credit the top-up; audited.

    Args:
        db: Session; the caller commits.
        hold_id: The open hold.
        admin_id: The deciding admin's user id.

    Returns:
        The hold, now ``released``.

    Raises:
        NotFoundError: ``hold_not_found``.
        ConflictError: ``hold_decided``.
    """
    row, payment, owner = await _decidable(db, hold_id)
    if isinstance(owner, Order):
        await mark_paid(db, owner, provider=payment.provider)
    else:
        owner.status = "succeeded"
        await credit_topup(
            db,
            user_id=owner.user_id,
            topup_id=owner.id,
            amount=owner.amount_uzs,
            provider=payment.provider,
        )
    return await _finish(db, row=row, payment=payment, decision="released", admin_id=admin_id)


async def mark_returned(db: AsyncSession, *, hold_id: str, admin_id: str) -> HoldOut:
    """«Вернул на карту»: the admin returned the money in the kassa; nothing is credited.

    Args:
        db: Session; the caller commits.
        hold_id: The open hold.
        admin_id: The deciding admin's user id.

    Returns:
        The hold, now ``returned``.

    Raises:
        NotFoundError: ``hold_not_found``.
        ConflictError: ``hold_decided``.
    """
    row, payment, owner = await _decidable(db, hold_id)
    move_payment(payment, "refunded")
    if isinstance(owner, Order):
        move_order(owner, "cancelled")
        await nudge(db, user_id=owner.user_id, number=owner.number)
    else:
        owner.status = "rejected"
    return await _finish(db, row=row, payment=payment, decision="returned", admin_id=admin_id)


__all__ = [
    "PAGE",
    "HoldOut",
    "HoldPage",
    "HoldState",
    "HoldUserOut",
    "list_holds",
    "mark_returned",
    "release",
]
