"""The admin's card payouts (spec 2026-10-08 §7): the queue, a request's page, reveal, paid,
reject, and the dashboard's «К выплате».

Writes lock the sale, then its request (the order :mod:`.status` takes), re-check under the
locks and flush; the route writes the audit row and the replay and commits. Only a ``to_pay``
request may be decided (409 ``payout_not_payable``): before ``completed`` no money is ours to
give. «Отклонить» credits the balance with the amount before the card fee
(``credit_payout_return``, keyed by the request). The full number leaves only through
:func:`reveal`, audited each time; it is never part of a page or a replay.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.cursor import decode_cursor, encode_cursor
from csmarket.core.errors import ConflictError, NotFoundError
from csmarket.core.logging import get_logger
from csmarket.modules.admin.api import record
from csmarket.modules.realtime.api import nudge_sale
from csmarket.modules.sales.admin_sales import (
    payout_row,
    sale_admin_out,
    sale_row,
    user_of,
    users_by_id,
)
from csmarket.modules.sales.admin_schemas import (
    PayoutCountsOut,
    PayoutDetailOut,
    PayoutRowOut,
    PayoutsPageOut,
)
from csmarket.modules.sales.cards import reveal_number
from csmarket.modules.sales.letters import enqueue_sale_letter
from csmarket.modules.sales.models import PayoutCard, PayoutRequest, Sale
from csmarket.modules.sales.payouts import request_of
from csmarket.modules.sales.schemas import PayoutStatusOut
from csmarket.modules.sales.status import lock_sale
from csmarket.modules.wallet.api import credit_payout_return

log = get_logger("csmarket.sales.admin")

#: How many of the seller's sales and payouts a request's page shows.
HISTORY = 20


def _not_payable() -> ConflictError:
    return ConflictError("this payout cannot be decided now", code="payout_not_payable")


async def _rows(db: AsyncSession, requests: list[PayoutRequest]) -> list[PayoutRowOut]:
    """Queue rows for ``requests``: sales, cards and users in one query each."""
    if not requests:
        return []
    numbers = dict(
        (
            await db.execute(
                select(Sale.id, Sale.number).where(Sale.id.in_({r.sale_id for r in requests}))
            )
        ).all()
    )
    cards = {
        c.id: c
        for c in await db.scalars(
            select(PayoutCard).where(PayoutCard.id.in_({r.card_id for r in requests}))
        )
    }
    users = await users_by_id(db, (r.user_id for r in requests))
    return [
        payout_row(
            r,
            number=numbers[r.sale_id],
            card=cards[r.card_id],
            user=user_of(users, r.user_id),
        )
        for r in requests
    ]


async def list_payouts(
    db: AsyncSession, *, status: PayoutStatusOut, cursor: str | None, limit: int
) -> PayoutsPageOut:
    """One status tab, newest first, and the count of every tab."""
    stmt = (
        select(PayoutRequest)
        .where(PayoutRequest.status == status)
        .order_by(PayoutRequest.created_at.desc(), PayoutRequest.id.desc())
        .limit(limit + 1)
    )
    if cursor is not None:
        stamp, rid = decode_cursor(cursor)
        stmt = stmt.where(
            (PayoutRequest.created_at < stamp)
            | ((PayoutRequest.created_at == stamp) & (PayoutRequest.id < rid))
        )
    found = list((await db.scalars(stmt)).all())
    page = found[:limit]
    counts = dict(
        (
            await db.execute(
                select(PayoutRequest.status, func.count()).group_by(PayoutRequest.status)
            )
        ).all()
    )
    return PayoutsPageOut(
        items=await _rows(db, page),
        counts=PayoutCountsOut(**{k: int(v) for k, v in counts.items()}),
        next_cursor=encode_cursor(page[-1].created_at, page[-1].id) if len(found) > limit else None,
    )


async def _request(db: AsyncSession, request_id: str) -> PayoutRequest:
    request = await db.get(PayoutRequest, request_id, populate_existing=True)
    if request is None:
        raise NotFoundError("payout request not found")
    return request


async def payout_detail(db: AsyncSession, request_id: str) -> PayoutDetailOut:
    """A request's page.

    Raises:
        NotFoundError: Unknown.
    """
    request = await _request(db, request_id)
    sale = await db.get(Sale, request.sale_id, populate_existing=True)
    if sale is None:  # the foreign key forbids it
        raise NotFoundError("sale not found")
    [row] = await _rows(db, [request])
    sales = (
        await db.scalars(
            select(Sale)
            .where(Sale.user_id == request.user_id)
            .order_by(Sale.created_at.desc())
            .limit(HISTORY)
        )
    ).all()
    payouts = (
        await db.scalars(
            select(PayoutRequest)
            .where(PayoutRequest.user_id == request.user_id)
            .order_by(PayoutRequest.created_at.desc())
            .limit(HISTORY)
        )
    ).all()
    users = await users_by_id(
        db, [request.user_id, *([request.paid_by] if request.paid_by else [])]
    )
    return PayoutDetailOut(
        request=row,
        note=request.note,
        reject_reason=request.reject_reason,
        decided_by=user_of(users, request.paid_by) if request.paid_by else None,
        sale=await sale_admin_out(db, sale),
        history_sales=[sale_row(s, user_of(users, s.user_id)) for s in sales],
        history_payouts=await _rows(db, list(payouts)),
        can_decide=request.status == "to_pay",
    )


async def reveal(
    db: AsyncSession, *, request_id: str, admin_id: str, purpose: Literal["show", "copy"]
) -> str:
    """The request's full card number, audited ``sales.card.<purpose>``; flushes.

    PII: the caller returns it to the admin and nowhere else.
    """
    request = await _request(db, request_id)
    card = await db.get(PayoutCard, request.card_id)
    if card is None:  # the foreign key forbids it
        raise NotFoundError("card not found")
    await record(
        db,
        actor_id=admin_id,
        action=f"sales.card.{purpose}",
        target_type="payout_request",
        target_id=request.id,
        payload={"last4": card.last4},
    )
    return reveal_number(card)


async def _locked(db: AsyncSession, request_id: str) -> tuple[Sale, PayoutRequest]:
    """The request's sale, then the request, ``FOR UPDATE``; a ``to_pay`` request only."""
    first = await _request(db, request_id)
    sale = await lock_sale(db, first.sale_id)
    request = await request_of(db, first.sale_id, lock=True)
    if sale is None or request is None:
        raise NotFoundError("payout request not found")
    if request.status != "to_pay":
        raise _not_payable()
    return sale, request


async def mark_paid(
    db: AsyncSession, *, request_id: str, admin_id: str, note: str | None
) -> PayoutRequest:
    """«Выплачено»: the admin paid the card by hand. Flushes.

    Raises:
        ConflictError: ``payout_not_payable``.
    """
    sale, request = await _locked(db, request_id)
    request.status, request.paid_by, request.paid_at, request.note = "paid", admin_id, now(), note
    card = await db.get(PayoutCard, request.card_id)
    await enqueue_sale_letter(
        db,
        sale,
        "sale_paid",
        amount_uzs=request.amount_uzs,
        to="card",
        last4=card.last4 if card else None,
    )
    await nudge_sale(db, user_id=sale.user_id, number=sale.number)
    await db.flush()
    log.info("sales.payout.paid", number=sale.number, amount_uzs=str(request.amount_uzs))
    return request


async def reject(db: AsyncSession, *, request_id: str, admin_id: str, reason: str) -> PayoutRequest:
    """«Отклонить»: the amount before the card fee goes to the seller's balance. Flushes.

    Raises:
        ConflictError: ``payout_not_payable``.
    """
    sale, request = await _locked(db, request_id)
    amount = request.amount_uzs + request.fee_uzs
    request.status, request.paid_by = "rejected", admin_id
    request.rejected_at, request.reject_reason = now(), reason
    await credit_payout_return(
        db,
        user_id=sale.user_id,
        sale_id=sale.id,
        request_id=request.id,
        amount=amount,
        actor=f"admin:{admin_id}",
    )
    await enqueue_sale_letter(db, sale, "sale_paid", amount_uzs=amount, to="balance")
    await nudge_sale(db, user_id=sale.user_id, number=sale.number)
    await db.flush()
    log.info("sales.payout.rejected", number=sale.number, amount_uzs=str(amount))
    return request


@dataclass(frozen=True)
class PayoutsSummary:
    """The dashboard's «К выплате»."""

    to_pay_count: int
    to_pay_uzs: Decimal


async def payouts_summary(db: AsyncSession) -> PayoutsSummary:
    """How many card payouts are payable now, and their sum."""
    count, total = (
        await db.execute(
            select(func.count(), func.coalesce(func.sum(PayoutRequest.amount_uzs), 0)).where(
                PayoutRequest.status == "to_pay"
            )
        )
    ).one()
    return PayoutsSummary(to_pay_count=int(count), to_pay_uzs=Decimal(total))


__all__ = [
    "PayoutsSummary",
    "list_payouts",
    "mark_paid",
    "payout_detail",
    "payouts_summary",
    "reject",
    "reveal",
]
