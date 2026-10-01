"""Click Shop API handlers for top-ups and orders: ``prepare``, ``complete``, ``cancel``.

Every money move goes through the ``payments`` hooks (``ensure_attempt``, ``mark_pending``,
``settle``, ``cancel_pending``); :class:`ClickTransaction` is only Click's own state machine.
The route verifies the MD5 signature before anything here runs.

The account (``merchant_trans_id``) is a payable number: a top-up's (``T…``) or an order's
(M4a); "owner" below is whichever it names.

**Lock order (global): owner (top-up or order) → Click row → payment → user wallet.**
``prepare`` resolves the owner with ``lock=True`` before it reads or inserts the Click row.
``complete`` and ``cancel`` start from a Click identifier: they read the row without a lock
to learn its account, lock the owner, then lock the row and re-check its status. The
timeout sweep scans unlocked, then per row locks the owner ``FOR UPDATE SKIP LOCKED``, then
the row.

An owner is paid at most once: a prepare on a paid top-up or order is ``-4``; a complete
whose owner was paid meanwhile (another kassa, or a sibling Click transaction sharing this
attempt) is ``-4`` and the transaction becomes ``CANCELLED``, so Click cancels that charge.
Click has no reversal of a completed payment, so an order's money never goes back through
Click (ruling R7).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.logging import get_logger
from csmarket.core.money import wire_uzs
from csmarket.modules.click.errors import (
    ClickError,
    already_paid,
    incorrect_amount,
    transaction_cancelled,
    transaction_not_found,
    user_not_found,
)
from csmarket.modules.click.models import ClickTransaction
from csmarket.modules.payments.api import (
    AlreadyPaidError,
    Payable,
    Payment,
    cancel_pending,
    ensure_attempt,
    lock_owner_or_skip,
    mark_pending,
    resolve,
    settle,
)

log = get_logger("csmarket.click.service")

PROVIDER = "click"
#: A ``PREPARED`` transaction Click has not completed in this long is cancelled by the sweep.
PREPARE_TIMEOUT = timedelta(minutes=30)

PREPARED, CONFIRMED, CANCELLED = "PREPARED", "CONFIRMED", "CANCELLED"

#: A Click answer body: ``error``, ``error_note`` and the echoed identifiers.
ClickResponse = dict[str, int | str]

#: Why the payable cannot be paid → the Click code.
_REFUSALS: dict[str, Callable[[], ClickError]] = {
    "not_found": user_not_found,
    "paid": already_paid,
    "expired": transaction_cancelled,
    "reversed": transaction_cancelled,
}

#: Payable reasons that mean its one payment is already taken.
_CREDITED = ("paid", "reversed")


def _amount_is(raw: str, expected: Decimal) -> bool:
    """Whether Click's raw ``amount`` (soʻm, e.g. ``"50000.00"``) equals ``expected``."""
    try:
        amount = Decimal(raw)
    except InvalidOperation:
        return False
    return amount.is_finite() and amount == expected


async def _txn_by_click(
    db: AsyncSession, *, click_trans_id: int, service_id: int, lock: bool = False
) -> ClickTransaction | None:
    stmt = select(ClickTransaction).where(
        ClickTransaction.click_trans_id == click_trans_id,
        ClickTransaction.service_id == service_id,
    )
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    return (await db.execute(stmt)).scalar_one_or_none()


async def _txn_by_prepare_id(db: AsyncSession, merchant_prepare_id: int) -> ClickTransaction | None:
    stmt = select(ClickTransaction).where(
        ClickTransaction.merchant_prepare_id == merchant_prepare_id
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def _lock_txn(db: AsyncSession, txn_id: str) -> ClickTransaction:
    """Re-read a known Click row ``FOR UPDATE`` (rows are never deleted)."""
    stmt = (
        select(ClickTransaction)
        .where(ClickTransaction.id == txn_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return (await db.execute(stmt)).scalar_one()


async def _payment(db: AsyncSession, payment_id: str) -> Payment:
    """The attempt, re-read: callers hold its owner, so its status is the committed one."""
    stmt = select(Payment).where(Payment.id == payment_id).execution_options(populate_existing=True)
    return (await db.execute(stmt)).scalar_one()


def _prepare_response(txn: ClickTransaction) -> ClickResponse:
    return {
        "click_trans_id": txn.click_trans_id,
        "merchant_trans_id": txn.account,
        "merchant_prepare_id": txn.merchant_prepare_id,
        "error": 0,
        "error_note": "Success",
    }


def _check_payable(payable: Payable) -> None:
    """``-5`` unknown, ``-4`` paid, ``-9`` expired or reversed."""
    if not payable.payable:
        raise _REFUSALS[payable.reason]()


async def _cancel_locked(db: AsyncSession, txn: ClickTransaction) -> None:
    """``PREPARED`` → ``CANCELLED``; the caller holds the owner and the row.

    The attempt is cancelled only when no other ``PREPARED`` Click row still holds it (a
    retried checkout shares one live attempt), and ``cancel_pending`` leaves an attempt a
    sibling already settled alone.
    """
    txn.status = CANCELLED
    txn.cancel_time = now()
    txn.updated_at = txn.cancel_time
    await db.flush()
    sibling = (
        await db.execute(
            select(ClickTransaction.id)
            .where(
                ClickTransaction.payment_id == txn.payment_id, ClickTransaction.status == PREPARED
            )
            .limit(1)
        )
    ).first()
    if sibling is None:
        await cancel_pending(db, payment=await _payment(db, txn.payment_id))


async def _refuse_second_charge(db: AsyncSession, txn: ClickTransaction) -> ClickError:
    """Cancel ``txn`` (kept: the route commits) and answer ``-4`` so Click cancels the charge."""
    await _cancel_locked(db, txn)
    log.warning(
        "click.complete.second_charge_refused", number=txn.account, amount=wire_uzs(txn.amount)
    )
    return ClickError(code=-4, note="Already paid", persist=True)


async def prepare(
    db: AsyncSession,
    *,
    click_trans_id: int,
    service_id: int,
    click_paydoc_id: int,
    merchant_trans_id: str,
    amount: str,
) -> ClickResponse:
    """``/prepare``: check the payable, hold an attempt, allocate a ``PREPARED`` row.

    Idempotent on ``(click_trans_id, service_id)``: a replay returns the same
    ``merchant_prepare_id``, also after a concurrent first call won the insert.

    Args:
        db: Session; the caller commits.
        click_trans_id: Click's transaction id.
        service_id: Our Click service (the route verified the signature with its secret).
        click_paydoc_id: Click's payment document id, kept for reconciliation.
        merchant_trans_id: The top-up or order number.
        amount: Click's raw ``amount`` in soʻm.

    Raises:
        ClickError: ``-5`` unknown, ``-4`` already paid, ``-9`` expired or reversed,
            ``-2`` amount not the top-up's ``amount_uzs`` / the order's ``price_uzs``.
    """
    payable = await resolve(db, merchant_trans_id, lock=True)
    existing = await _txn_by_click(
        db, click_trans_id=click_trans_id, service_id=service_id, lock=True
    )
    if existing is not None:
        return _prepare_response(existing)
    _check_payable(payable)
    if not _amount_is(amount, payable.amount_uzs):
        raise incorrect_amount()
    # SAVEPOINT: two first-time prepares with one (click_trans_id, service_id) but different
    # accounts lock different owners, so both can reach this insert; the loser re-reads the
    # winner's row and answers the same success (Click's replay contract). The attempt work
    # sits inside it too, so the loser's owner is not left with a ``pending`` attempt that no
    # Click row holds (no sweep would ever release it).
    try:
        async with db.begin_nested():
            try:
                payment = await ensure_attempt(db, payable=payable, provider=PROVIDER)
            except AlreadyPaidError:  # pragma: no cover - _check_payable refused it under the lock
                raise already_paid() from None
            await mark_pending(db, payment=payment)
            txn = ClickTransaction(
                click_trans_id=click_trans_id,
                service_id=service_id,
                payment_id=payment.id,
                account=payable.number,
                amount=payable.amount_uzs,
                status=PREPARED,
                click_paydoc_id=click_paydoc_id,
                prepare_time=now(),
            )
            db.add(txn)
            await db.flush()
    except IntegrityError:
        winner = await _txn_by_click(db, click_trans_id=click_trans_id, service_id=service_id)
        if winner is None:  # pragma: no cover - the unique pair collided, so the row exists
            raise
        return _prepare_response(winner)
    return _prepare_response(txn)


async def complete(
    db: AsyncSession,
    *,
    click_trans_id: int,
    service_id: int,
    merchant_trans_id: str,
    merchant_prepare_id: int,
    amount: str,
) -> ClickResponse:
    """``/complete``: Click debited the customer — settle the attempt, pay the owner once.

    Args:
        db: Session; the caller commits (also on a ``persist`` error).
        click_trans_id: Must match the prepared row.
        service_id: Must match the prepared row.
        merchant_trans_id: Must match the prepared row's account.
        merchant_prepare_id: The id we answered at prepare time; the lookup key.
        amount: Click's raw ``amount`` in soʻm; must equal the prepared amount.

    Raises:
        ClickError: ``-6`` unknown or mismatched, ``-4`` already confirmed or the owner
            already paid (then the row is cancelled and ``persist`` is set), ``-9``
            cancelled, ``-2`` amount mismatch.
    """
    seen = await _txn_by_prepare_id(db, merchant_prepare_id)
    if (
        seen is None
        or seen.click_trans_id != click_trans_id
        or seen.service_id != service_id
        or seen.account != merchant_trans_id
    ):
        raise transaction_not_found()
    payable = await resolve(db, seen.account, lock=True)
    txn = await _lock_txn(db, seen.id)
    if txn.status == CONFIRMED:
        raise already_paid()
    if txn.status == CANCELLED:
        raise transaction_cancelled()
    if not _amount_is(amount, txn.amount):
        raise incorrect_amount()
    payment = await _payment(db, txn.payment_id)
    # Paid through another kassa, or through a sibling Click row sharing this attempt
    # (then ``settle`` would be a no-op success): either way this charge is a second one.
    if payable.reason in _CREDITED or payment.status == "succeeded":
        raise await _refuse_second_charge(db, txn)
    try:
        await settle(db, payment=payment, event_id=f"click:{click_trans_id}")
    except AlreadyPaidError:  # pragma: no cover - refused above under the same owner lock
        raise await _refuse_second_charge(db, txn) from None
    txn.status = CONFIRMED
    txn.complete_time = now()
    txn.updated_at = txn.complete_time
    await db.flush()
    return {
        "click_trans_id": txn.click_trans_id,
        "merchant_trans_id": txn.account,
        "merchant_confirm_id": txn.merchant_prepare_id,
        "error": 0,
        "error_note": "Success",
    }


async def cancel(
    db: AsyncSession,
    *,
    merchant_prepare_id: int | None = None,
    click_trans_id: int | None = None,
    service_id: int | None = None,
) -> None:
    """Click aborted (a negative inbound ``error``): cancel the ``PREPARED`` row.

    Found by ``merchant_prepare_id`` (``/complete``) or by ``(click_trans_id, service_id)``
    (``/prepare``, where Click has no prepare id yet). A no-op when there is no such row or
    it is not ``PREPARED`` — a ``CONFIRMED`` row is never touched (Click has no
    merchant-initiated reversal).

    Raises:
        ValueError: neither lookup key was given.
    """
    if merchant_prepare_id is not None:
        seen = await _txn_by_prepare_id(db, merchant_prepare_id)
    elif click_trans_id is not None and service_id is not None:
        seen = await _txn_by_click(db, click_trans_id=click_trans_id, service_id=service_id)
    else:
        raise ValueError("cancel() requires merchant_prepare_id or (click_trans_id, service_id)")
    if seen is None or seen.status != PREPARED:
        return
    await resolve(db, seen.account, lock=True)
    txn = await _lock_txn(db, seen.id)
    if txn.status != PREPARED:
        return
    await _cancel_locked(db, txn)
    log.info("click.cancelled", number=txn.account, amount=wire_uzs(txn.amount))


async def cancel_stale(db: AsyncSession, *, limit: int = 500) -> int:
    """Cancel ``PREPARED`` rows Click has not completed within :data:`PREPARE_TIMEOUT`.

    Covers top-up and order attempts alike. The scan reads unlocked; per row, in its own
    savepoint, the owner (top-up or order) is locked ``FOR UPDATE SKIP LOCKED`` — one a
    callback holds is left for the next tick — then the row is re-read ``FOR UPDATE`` and
    re-checked, so a ``/complete`` that landed meanwhile is never clobbered. An order's
    status is never touched (its expiry sweep owns it). One failing row does not stop the
    rest. Flushes, never commits.

    Returns:
        How many rows went ``CANCELLED``.
    """
    stmt = (
        select(ClickTransaction.id, ClickTransaction.payment_id)
        .where(
            ClickTransaction.status == PREPARED,
            ClickTransaction.prepare_time < now() - PREPARE_TIMEOUT,
        )
        .order_by(ClickTransaction.prepare_time)
        .limit(limit)
    )
    cancelled = 0
    for txn_id, payment_id in (await db.execute(stmt)).all():
        try:
            async with db.begin_nested():
                if not await lock_owner_or_skip(db, payment_id=payment_id):
                    continue
                txn = await _lock_txn(db, txn_id)
                if txn.status != PREPARED:
                    continue
                await _cancel_locked(db, txn)
        except Exception:  # one bad row must not stop the sweep
            log.exception("click.timeout.row_failed", click_txn_id=txn_id)
            continue
        cancelled += 1
    return cancelled


__all__ = [
    "PREPARE_TIMEOUT",
    "PROVIDER",
    "ClickResponse",
    "cancel",
    "cancel_stale",
    "complete",
    "prepare",
]
