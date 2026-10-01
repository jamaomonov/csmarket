"""Uzum Bank Merchant API handlers for balance top-ups.

The five webhooks Uzum calls — ``/check``, ``/create``, ``/confirm``, ``/reverse``,
``/status`` — plus the 30-minute timeout sweep. Every money move goes through the
``payments`` hooks (``ensure_attempt``, ``mark_pending``, ``settle``, ``reverse``,
``cancel_pending``); :class:`UzumTransaction` is only Uzum's state machine, which we own.
Unlike Payme, Uzum signals a replay with a dedicated code (10010 / 10016 / 10018), not an
echo. The route checks Basic auth and ``serviceId`` before anything here runs.

**Lock order (global): top-up → Uzum row → payment → user wallet.** ``/check`` and
``/create`` resolve the top-up with ``lock=True`` first. ``/confirm`` and ``/reverse`` start
from a ``transId``: they read the row without a lock to learn its account, lock the top-up,
then lock the row and re-check its status. ``/status`` only reads. The timeout sweep locks
top-ups ``FOR UPDATE SKIP LOCKED`` in its scan, then each row.

A top-up is credited at most once: ``/create`` on a paid top-up is 10008; ``/confirm`` after
the top-up was paid meanwhile (another kassa, or a sibling Uzum row sharing this attempt)
is 10008 and the transaction is FAILED and committed, so Uzum drops that charge.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.logging import get_logger
from csmarket.core.money import wire_uzs
from csmarket.modules.payments.api import (
    AlreadyPaidError,
    Payable,
    Payment,
    TopupSpentError,
    WalletTopup,
    cancel_pending,
    ensure_attempt,
    mark_pending,
    resolve,
    settle,
)
from csmarket.modules.payments.api import reverse as reverse_payment
from csmarket.modules.uzum.errors import (
    UzumError,
    account_not_found,
    invalid_amount,
    payment_already_made,
    payment_cancelled,
    transaction_already_cancelled,
    transaction_already_confirmed,
    transaction_already_created,
    transaction_cancelled,
    transaction_cannot_be_cancelled,
    transaction_not_found,
)
from csmarket.modules.uzum.models import (
    STATUS_CONFIRMED,
    STATUS_CREATED,
    STATUS_FAILED,
    STATUS_REVERSED,
    UzumTransaction,
)

log = get_logger("csmarket.uzum.service")

PROVIDER = "uzum"
#: A CREATED transaction Uzum has not confirmed or reversed in this long is FAILED
#: (Uzum's own spec, §10).
TIMEOUT = timedelta(minutes=30)

#: A webhook's success body, before the route adds ``serviceId``.
Result = dict[str, Any]

#: Why the payable cannot be paid → the Uzum code.
_REFUSALS: dict[str, Callable[[], UzumError]] = {
    "not_found": account_not_found,
    "paid": payment_already_made,
    "expired": payment_cancelled,
    "reversed": payment_cancelled,
}

#: Top-up reasons that mean its one credit is already taken.
_CREDITED = ("paid", "reversed")


def now_ms() -> int:
    """The current time as Uzum epoch milliseconds."""
    return int(now().timestamp() * 1000)


def _check_payable(payable: Payable) -> None:
    """10007 unknown, 10008 paid, 10009 expired / reversed."""
    if not payable.payable:
        raise _REFUSALS[payable.reason]()


def _tiyin(payable: Payable) -> int:
    """The top-up's amount in tiyin (whole soʻm × 100, exact)."""
    return int(payable.amount_uzs * 100)


async def _txn_by_trans_id(db: AsyncSession, trans_id: str) -> UzumTransaction | None:
    """The row for ``trans_id``, read without a lock."""
    stmt = select(UzumTransaction).where(UzumTransaction.trans_id == trans_id)
    return (await db.execute(stmt)).scalar_one_or_none()


async def _lock_txn(db: AsyncSession, txn_id: str) -> UzumTransaction:
    """Re-read a known Uzum row ``FOR UPDATE`` (rows are never deleted)."""
    stmt = (
        select(UzumTransaction)
        .where(UzumTransaction.id == txn_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return (await db.execute(stmt)).scalar_one()


async def _locked_by_trans_id(db: AsyncSession, trans_id: str) -> tuple[Payable, UzumTransaction]:
    """The row named by ``trans_id``, locked in the global order: top-up, then the row.

    Raises:
        UzumError: 10014 when there is no such row.
    """
    seen = await _txn_by_trans_id(db, trans_id)
    if seen is None:
        raise transaction_not_found()
    payable = await resolve(db, seen.account, lock=True)
    return payable, await _lock_txn(db, seen.id)


async def _payment(db: AsyncSession, payment_id: str) -> Payment:
    """The attempt, re-read: callers hold its top-up, so its status is the committed one."""
    stmt = select(Payment).where(Payment.id == payment_id).execution_options(populate_existing=True)
    return (await db.execute(stmt)).scalar_one()


async def _release_attempt(db: AsyncSession, txn: UzumTransaction) -> None:
    """Cancel ``txn``'s attempt unless another CREATED Uzum row still holds it.

    ``cancel_pending`` also leaves an attempt a sibling already settled alone.
    """
    sibling = (
        await db.execute(
            select(UzumTransaction.id)
            .where(
                UzumTransaction.payment_id == txn.payment_id,
                UzumTransaction.status == STATUS_CREATED,
                UzumTransaction.id != txn.id,
            )
            .limit(1)
        )
    ).first()
    if sibling is None:
        await cancel_pending(db, payment=await _payment(db, txn.payment_id))


async def _fail_created(db: AsyncSession, txn: UzumTransaction) -> None:
    """CREATED → FAILED and release the attempt; the caller holds the top-up and the row."""
    txn.status = STATUS_FAILED
    txn.updated_at = now()
    await db.flush()
    await _release_attempt(db, txn)


async def _refuse_second_charge(db: AsyncSession, txn: UzumTransaction) -> UzumError:
    """Fail ``txn`` (kept: the route commits) and answer 10008 so Uzum drops the charge."""
    await _fail_created(db, txn)
    log.warning(
        "uzum.confirm.second_charge_refused",
        number=txn.account,
        amount=wire_uzs(Decimal(txn.amount_tiyin) / 100),
    )
    return payment_already_made(persist=True)


async def check(db: AsyncSession, *, account: str) -> Result:
    """``/check``: may this top-up be paid? Reports its amount for Uzum's app to prefill.

    Returns:
        ``{"status": "OK", "data": {"amount": {"value": <whole soʻm as a string>}}}`` —
        soʻm here, unlike every ``amount`` field, which is tiyin.

    Raises:
        UzumError: 10007 unknown, 10008 paid, 10009 expired / reversed.
    """
    payable = await resolve(db, account, lock=True)
    _check_payable(payable)
    return {"status": "OK", "data": {"amount": {"value": wire_uzs(payable.amount_uzs)}}}


async def create(
    db: AsyncSession, *, service_id: int, trans_id: str, account: str, amount: int
) -> Result:
    """``/create``: hold an attempt and register Uzum's transaction (``CREATED``).

    A ``transId`` we already have is refused with 10010 whatever its state or account
    (Uzum's replay code); the row is only read, never locked, so a ``transId`` of another
    top-up is never locked while we hold this one. The attempt work and the insert share one
    SAVEPOINT, so losing the insert race leaves no attempt ``pending``. A second
    ``transId`` on the same top-up (a retried checkout) shares its live attempt.

    Args:
        db: Session; the caller commits.
        service_id: Our ``serviceId`` (already checked), stored for audit.
        trans_id: Uzum's transaction id (unique) — the replay key.
        account: The top-up number Uzum sent.
        amount: Tiyin.

    Raises:
        UzumError: 10010 replay; 10007 / 10008 / 10009 as ``/check``; 10011 amount.
    """
    payable = await resolve(db, account, lock=True)
    if await _txn_by_trans_id(db, trans_id) is not None:
        raise transaction_already_created()
    _check_payable(payable)
    if amount != _tiyin(payable):
        raise invalid_amount()
    try:
        async with db.begin_nested():
            try:
                payment = await ensure_attempt(db, payable=payable, provider=PROVIDER)
            except AlreadyPaidError:  # pragma: no cover - refused above under the same lock
                raise payment_already_made() from None
            await mark_pending(db, payment=payment)
            txn = UzumTransaction(
                trans_id=trans_id,
                payment_id=payment.id,
                account=payable.number,
                amount_tiyin=amount,
                status=STATUS_CREATED,
                service_id=service_id,
                create_time=now_ms(),
            )
            db.add(txn)
            await db.flush()
    except IntegrityError:
        # A concurrent /create with this transId won the insert (any account): Uzum's replay
        # code. Anything else that broke the insert stays an internal error.
        if await _txn_by_trans_id(db, trans_id) is None:  # pragma: no cover - not reachable
            raise
        raise transaction_already_created() from None
    log.info("uzum.created", number=payable.number, amount=wire_uzs(payable.amount_uzs))
    return {
        "transId": trans_id,
        "status": STATUS_CREATED,
        "transTime": txn.create_time,
        "amount": amount,
    }


async def confirm(db: AsyncSession, *, trans_id: str, payment_source: dict[str, Any]) -> Result:
    """``/confirm``: Uzum debited the customer — settle, credit the top-up once.

    If the top-up was credited meanwhile (another kassa, or a sibling Uzum row on this
    attempt), this charge is refused with 10008 and the transaction goes ``FAILED`` —
    ``persist`` is set so the route commits that.

    Args:
        db: Session; the caller commits.
        trans_id: Uzum's transaction id.
        payment_source: Uzum's extras (``paymentSource``, ``phone``, …), stored for audit.
            Holds the payer's phone: never log it.

    Raises:
        UzumError: 10014 unknown, 10016 already confirmed, 10015 reversed / failed,
            10008 a second charge.
    """
    payable, txn = await _locked_by_trans_id(db, trans_id)
    if txn.status == STATUS_CONFIRMED:
        raise transaction_already_confirmed()
    if txn.status != STATUS_CREATED:
        raise transaction_cancelled()
    txn.payment_source = payment_source
    payment = await _payment(db, txn.payment_id)
    if payable.reason in _CREDITED or payment.status == "succeeded":
        raise await _refuse_second_charge(db, txn)
    try:
        await settle(db, payment=payment, event_id=f"uzum:{trans_id}")
    except AlreadyPaidError:  # pragma: no cover - refused above under the same top-up lock
        raise await _refuse_second_charge(db, txn) from None
    txn.status = STATUS_CONFIRMED
    txn.confirm_time = now_ms()
    txn.updated_at = now()
    await db.flush()
    log.info("uzum.confirmed", number=txn.account, amount=wire_uzs(payable.amount_uzs))
    return {
        "transId": trans_id,
        "status": STATUS_CONFIRMED,
        "confirmTime": txn.confirm_time,
        "amount": txn.amount_tiyin,
    }


async def reverse(db: AsyncSession, *, trans_id: str) -> Result:
    """``/reverse``, routed by the transaction's status.

    ``CREATED`` → the attempt is released (unless another CREATED row holds it).
    ``FAILED`` → its attempt was already released; only the row closes. ``CONFIRMED`` → the
    top-up is reversed if its money is still on the balance; otherwise 10017 and nothing
    changes (ruling R7).

    Raises:
        UzumError: 10014 unknown, 10018 already reversed, 10017 the top-up was spent.
    """
    _, txn = await _locked_by_trans_id(db, trans_id)
    previous = txn.status
    if previous == STATUS_REVERSED:
        raise transaction_already_cancelled()
    if txn.status == STATUS_CONFIRMED:
        try:
            await reverse_payment(
                db, payment=await _payment(db, txn.payment_id), event_id=f"uzum:{trans_id}"
            )
        except TopupSpentError:
            raise transaction_cannot_be_cancelled() from None
    elif txn.status == STATUS_CREATED:
        await _release_attempt(db, txn)
    txn.status = STATUS_REVERSED
    txn.reverse_time = now_ms()
    txn.updated_at = now()
    await db.flush()
    log.info(
        "uzum.reversed",
        number=txn.account,
        amount=wire_uzs(Decimal(txn.amount_tiyin) / 100),
        status_was=previous,
    )
    return {
        "transId": trans_id,
        "status": STATUS_REVERSED,
        "reverseTime": txn.reverse_time,
        "amount": txn.amount_tiyin,
    }


async def status(db: AsyncSession, *, trans_id: str) -> Result:
    """``/status``: the transaction's status and times (a plain read).

    Uzum polls it (up to 10 times) after a ``/confirm`` whose answer it lost; a confirm
    commits before it answers, so this always sees it.

    Raises:
        UzumError: 10014 unknown.
    """
    txn = await _txn_by_trans_id(db, trans_id)
    if txn is None:
        raise transaction_not_found()
    return {
        "transId": trans_id,
        "status": txn.status,
        "transTime": txn.create_time,
        "confirmTime": txn.confirm_time,
        "reverseTime": txn.reverse_time,
        "data": {},
        "amount": txn.amount_tiyin,
    }


async def fail_stale(db: AsyncSession, *, limit: int = 500) -> int:
    """FAIL CREATED transactions Uzum left untouched for :data:`TIMEOUT`.

    The scan locks the rows' top-ups ``FOR UPDATE SKIP LOCKED`` (one a callback holds is
    left for the next tick), then each row is re-read ``FOR UPDATE`` and re-checked: a
    ``/confirm`` that landed meanwhile is never clobbered. Each row runs in its own
    savepoint, so one failure does not stop the rest. Flushes, never commits.

    Returns:
        How many transactions went to ``FAILED``.
    """
    cutoff = now_ms() - int(TIMEOUT.total_seconds() * 1000)
    stmt = (
        select(UzumTransaction.id)
        .join(Payment, Payment.id == UzumTransaction.payment_id)
        .join(WalletTopup, WalletTopup.id == Payment.topup_id)
        .where(UzumTransaction.status == STATUS_CREATED, UzumTransaction.create_time < cutoff)
        .order_by(UzumTransaction.create_time)
        .limit(limit)
        .with_for_update(of=WalletTopup, skip_locked=True)
    )
    failed = 0
    for txn_id in list((await db.execute(stmt)).scalars()):
        try:
            async with db.begin_nested():
                txn = await _lock_txn(db, txn_id)
                if txn.status != STATUS_CREATED:
                    continue
                await _fail_created(db, txn)
        except Exception:  # one bad row must not stop the sweep
            log.exception("uzum.timeout.row_failed", uzum_txn_id=txn_id)
            continue
        failed += 1
    return failed


__all__ = [
    "PROVIDER",
    "TIMEOUT",
    "Result",
    "check",
    "confirm",
    "create",
    "fail_stale",
    "now_ms",
    "reverse",
    "status",
]
