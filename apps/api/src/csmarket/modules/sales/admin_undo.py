"""«Вернуть в очередь»: undo a wrong «Выплачено» or «Отклонить» within
:data:`~.admin_payouts.UNDO_WINDOW` (admin review 2026-10-12 M5).

- A ``paid`` request goes back to ``to_pay``: nothing moved on our ledger (the card was paid
  outside it), so only the stamps are cleared. If the money really went out, do not undo.
- A ``rejected`` request goes back to ``to_pay`` only if its credit can be taken back: the
  wallet is locked, the balance must still cover the whole credit (409 ``balance_spent``
  otherwise — the seller may have spent it, and our code never drives a balance below zero),
  and a frozen wallet refuses (409 ``wallet_frozen``). The reversal is its own ledger
  transaction (``payout_return_reversal``), keyed by the request and its undo count, and a
  second «Отклонить» afterwards credits under a new key.

The seller's letter about the undone decision is dropped if it is still waiting in the
outbox; one already sent stays sent (the runbook says what to tell the seller). Audited
``sales.payout.undo`` by the route; flush, never commit.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.errors import ConflictError
from csmarket.core.logging import get_logger
from csmarket.modules.notifications.api import discard_pending
from csmarket.modules.realtime.api import nudge_sale
from csmarket.modules.sales.admin_payouts import locked, undo_until
from csmarket.modules.sales.admin_risk import frozen_users
from csmarket.modules.sales.models import PayoutRequest
from csmarket.modules.wallet.api import debit_payout_return

log = get_logger("csmarket.sales.admin_undo")


async def undo(db: AsyncSession, *, request_id: str, admin_id: str) -> tuple[PayoutRequest, str]:
    """Put a request decided minutes ago back into «К выплате». Flushes.

    Returns:
        The request and the status it was undone from (``paid`` / ``rejected``).

    Raises:
        ConflictError: ``undo_expired`` (not decided, or decided too long ago),
            ``undo_not_yours`` (a «Выплачено» marked by another admin), ``balance_spent``,
            ``wallet_frozen``, ``payout_claimed``.
    """
    sale, request = await locked(db, request_id, admin_id=admin_id, status=None)
    if undo_until(request) is None:
        raise ConflictError("this decision can no longer be undone", code="undo_expired")
    was = request.status
    if was == "paid" and request.paid_by != admin_id:
        # Only the admin who sent the transfer knows it did not go out; another admin's undo
        # followed by «Отклонить» or a second «Выплачено» could pay the seller twice.
        raise ConflictError("only the admin who marked it paid can undo it", code="undo_not_yours")
    if was == "rejected":
        if request.user_id in await frozen_users(db, [request.user_id]):
            raise ConflictError("the seller's wallet is frozen", code="wallet_frozen")
        await debit_payout_return(
            db,
            user_id=request.user_id,
            sale_id=sale.id,
            request_id=request.id,
            amount=request.amount_uzs + request.fee_uzs,
            actor=f"admin:{admin_id}",
            attempt=request.undo_count,
        )
    request.status, request.paid_by, request.paid_at, request.note = "to_pay", None, None, None
    request.rejected_at, request.reject_reason = None, None
    request.undo_count += 1
    await discard_pending(db, sale_id=sale.id, kind="sale_paid")
    await nudge_sale(db, user_id=sale.user_id, number=sale.number)
    await db.flush()
    log.info("sales.payout.undone", number=sale.number, was=was)
    return request, was


__all__ = ["undo"]
