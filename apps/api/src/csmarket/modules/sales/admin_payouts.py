"""The admin's card payouts (spec 2026-10-08 §7): the queue, a request's page, reveal, paid,
reject, and the dashboard's «К выплате».

Writes lock the sale, then its request (the order :mod:`.status` takes), re-check under the
locks and flush; the route writes the audit row and the replay and commits. Only a ``to_pay``
request may be decided (409 ``payout_not_payable``): before ``completed`` no money is ours to
give. «Отклонить» credits the balance with the amount before the card fee
(``credit_payout_return``, keyed by the request). The full number leaves only through
:func:`reveal`, audited each time; it is never part of a page or a replay.

Before money moves an admin claims the request («Беру в работу», :mod:`.admin_claims`); a
reveal claims a free one on the way, and another admin's live claim refuses the reveal and
every decision (409 ``payout_claimed``). «Выплачено» to a banned account or a frozen wallet
is refused (409 ``payout_user_blocked``) unless the admin gives an ``override_reason``
(audited); «Отклонить» to a frozen wallet is 409 ``wallet_frozen`` before anything moves.
The queue and the totals live in :mod:`.admin_queue`, the undo in :mod:`.admin_undo`.

A Skinslink revert after the request became payable never cancels it (the admin may be paying
it right now, review SB-3 / M7): the sale is flagged ``rolled_back`` and the request stays
``to_pay``. «Выплачено» still records a transfer that went out; «Отменить (откат)»
(:func:`cancel_rolled_back`) closes it unpaid.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.errors import ConflictError, NotFoundError
from csmarket.core.logging import get_logger
from csmarket.modules.admin.api import record
from csmarket.modules.realtime.api import nudge_sale
from csmarket.modules.sales import admin_claims
from csmarket.modules.sales.admin_queue import PayoutsSummary, list_payouts, payouts_summary, rows
from csmarket.modules.sales.admin_risk import frozen_users, payout_risk
from csmarket.modules.sales.admin_sales import sale_admin_out, sale_row, user_of, users_by_id
from csmarket.modules.sales.admin_schemas import PayoutDetailOut
from csmarket.modules.sales.cards import reveal_number
from csmarket.modules.sales.letters import enqueue_sale_letter
from csmarket.modules.sales.models import PayoutCard, PayoutRequest, Sale
from csmarket.modules.sales.payouts import request_of
from csmarket.modules.sales.status import lock_sale
from csmarket.modules.users.api import User
from csmarket.modules.wallet.api import credit_payout_return

log = get_logger("csmarket.sales.admin")

#: How many of the seller's sales and payouts a request's page shows.
HISTORY = 20
#: How long a «Выплачено» or «Отклонить» may be undone (``admin_undo``).
UNDO_WINDOW = timedelta(minutes=10)


def _not_payable() -> ConflictError:
    return ConflictError("this payout cannot be decided now", code="payout_not_payable")


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
    [row] = await rows(db, [request])
    card = await db.get(PayoutCard, request.card_id)
    if card is None:  # the foreign key forbids it
        raise NotFoundError("card not found")
    risk = await payout_risk(db, request, card)
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
        history_payouts=await rows(db, [p for p in payouts if p.id != request.id]),
        can_decide=request.status == "to_pay",
        can_cancel=_cancelable(sale, request),
        undo_until=undo_until(request),
        paid_needs_override=request.status == "to_pay" and (risk.banned or risk.wallet_frozen),
        risk=risk,
    )


def undo_until(request: PayoutRequest, at: datetime | None = None) -> datetime | None:
    """Until when the request's decision may be undone; ``None`` when it may not."""
    decided = {"paid": request.paid_at, "rejected": request.rejected_at}.get(request.status)
    if decided is None:
        return None
    until = decided + UNDO_WINDOW
    return until if until > (at or now()) else None


def _cancelable(sale: Sale, request: PayoutRequest) -> bool:
    """«Отменить (откат)»: a payable request whose sale Skinslink reverted afterwards."""
    return request.status == "to_pay" and sale.attention_reason == "rolled_back"


async def reveal(
    db: AsyncSession, *, request_id: str, admin_id: str, purpose: Literal["show", "copy"]
) -> str:
    """The request's full card number, audited ``sales.card.<purpose>``; claims a free
    ``to_pay`` request for the admin on the way. Flushes.

    PII: the caller returns it to the admin and nowhere else.

    Raises:
        ConflictError: ``payout_claimed`` — another admin is paying it; ``payout_not_payable``
            — the request is decided or not payable yet: its number is no longer needed.
    """
    first = await _request(db, request_id)
    await lock_sale(db, first.sale_id)
    request = await request_of(db, first.sale_id, lock=True)
    if request is None:
        raise NotFoundError("payout request not found")
    if request.status != "to_pay":
        raise _not_payable()
    await admin_claims.take(db, request, admin_id=admin_id)
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


async def locked(
    db: AsyncSession, request_id: str, *, admin_id: str, status: str | None = "to_pay"
) -> tuple[Sale, PayoutRequest]:
    """The request's sale, then the request, ``FOR UPDATE``; ``status`` only (``None``: any),
    and not held by another admin.

    Raises:
        NotFoundError: Unknown.
        ConflictError: ``payout_not_payable``, ``payout_claimed``.
    """
    first = await _request(db, request_id)
    sale = await lock_sale(db, first.sale_id)
    request = await request_of(db, first.sale_id, lock=True)
    if sale is None or request is None:
        raise NotFoundError("payout request not found")
    if status is not None and request.status != status:
        raise _not_payable()
    admin_claims.ensure_free_for(request, admin_id)
    return sale, request


async def claim(
    db: AsyncSession, *, request_id: str, admin_id: str, takeover: bool
) -> PayoutRequest:
    """«Беру в работу» (``takeover``: from another admin). Flushes.

    Raises:
        ConflictError: ``payout_not_payable``, ``payout_claimed``.
    """
    first = await _request(db, request_id)
    await lock_sale(db, first.sale_id)
    request = await request_of(db, first.sale_id, lock=True)
    if request is None:
        raise NotFoundError("payout request not found")
    if request.status != "to_pay":
        raise _not_payable()
    await admin_claims.take(db, request, admin_id=admin_id, takeover=takeover)
    return request


async def release(db: AsyncSession, *, request_id: str, admin_id: str) -> PayoutRequest:
    """«Отпустить»: the claimer gives the request back. Flushes.

    Raises:
        ConflictError: ``payout_claimed`` — someone else holds it.
    """
    _, request = await locked(db, request_id, admin_id=admin_id, status=None)
    await admin_claims.release(db, request, admin_id=admin_id)
    return request


async def _user_blocked(db: AsyncSession, user_id: str) -> bool:
    """The account is banned or its soʻm wallet frozen."""
    banned = await db.scalar(select(User.banned_at).where(User.id == user_id))
    return banned is not None or user_id in await frozen_users(db, [user_id])


async def mark_paid(
    db: AsyncSession,
    *,
    request_id: str,
    admin_id: str,
    note: str | None,
    override_reason: str | None = None,
) -> tuple[PayoutRequest, bool]:
    """«Выплачено»: the admin paid the card by hand. Flushes.

    Returns:
        The request, and whether the banned / frozen check was overridden.

    Raises:
        ConflictError: ``payout_not_payable``, ``payout_claimed``, ``payout_user_blocked``
            (a banned account or a frozen wallet, and no ``override_reason``).
    """
    sale, request = await locked(db, request_id, admin_id=admin_id)
    overridden = False
    if await _user_blocked(db, request.user_id):
        if not (override_reason and override_reason.strip()):
            raise ConflictError(
                "the account is banned or its wallet frozen", code="payout_user_blocked"
            )
        overridden = True
    request.status, request.paid_by, request.paid_at, request.note = "paid", admin_id, now(), note
    admin_claims.clear(request)
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
    return request, overridden


async def reject(db: AsyncSession, *, request_id: str, admin_id: str, reason: str) -> PayoutRequest:
    """«Отклонить»: the amount before the card fee goes to the seller's balance. Flushes.

    Raises:
        ConflictError: ``payout_not_payable``, ``payout_claimed``, ``wallet_frozen`` (the
            seller's wallet is frozen: nothing can be credited; pay the card or unfreeze).
    """
    sale, request = await locked(db, request_id, admin_id=admin_id)
    if request.user_id in await frozen_users(db, [request.user_id]):
        raise ConflictError("the seller's wallet is frozen", code="wallet_frozen")
    amount = request.amount_uzs + request.fee_uzs
    request.status, request.paid_by = "rejected", admin_id
    request.rejected_at, request.reject_reason = now(), reason
    admin_claims.clear(request)
    await credit_payout_return(
        db,
        user_id=sale.user_id,
        sale_id=sale.id,
        request_id=request.id,
        amount=amount,
        actor=f"admin:{admin_id}",
        attempt=request.undo_count,
    )
    card = await db.get(PayoutCard, request.card_id)
    await enqueue_sale_letter(
        db,
        sale,
        "sale_paid",
        amount_uzs=amount,
        to="balance",
        last4=card.last4 if card else None,
        rejected=True,
    )
    await nudge_sale(db, user_id=sale.user_id, number=sale.number)
    await db.flush()
    log.info("sales.payout.rejected", number=sale.number, amount_uzs=str(amount))
    return request


async def cancel_rolled_back(
    db: AsyncSession, *, request_id: str, admin_id: str, reason: str
) -> PayoutRequest:
    """«Отменить (откат)»: the sale was reverted after it became payable and the admin did not
    pay; the request is canceled, the sale ``reverted``, its attention marked checked and the
    seller gets the canceled letter. Flushes.

    Raises:
        ConflictError: ``payout_not_payable`` (not ``to_pay``), ``payout_not_cancelable``
            (the sale was not reverted), ``payout_claimed``.
    """
    sale, request = await locked(db, request_id, admin_id=admin_id)
    if not _cancelable(sale, request):
        raise ConflictError(
            "only a payout whose sale was reverted can be canceled", code="payout_not_cancelable"
        )
    at = now()
    request.status, request.paid_by, request.note = "canceled", admin_id, reason
    admin_claims.clear(request)
    sale.status, sale.fail_reason = "reverted", "reverted"
    sale.resolved_at, sale.resolved_by, sale.resolved_note = at, admin_id, reason
    await enqueue_sale_letter(db, sale, "sale_canceled")
    await nudge_sale(db, user_id=sale.user_id, number=sale.number)
    await db.flush()
    log.info("sales.payout.canceled", number=sale.number, amount_uzs=str(request.amount_uzs))
    return request


__all__ = [
    "UNDO_WINDOW",
    "PayoutsSummary",
    "cancel_rolled_back",
    "claim",
    "list_payouts",
    "locked",
    "mark_paid",
    "payout_detail",
    "payouts_summary",
    "reject",
    "release",
    "reveal",
    "undo_until",
]
