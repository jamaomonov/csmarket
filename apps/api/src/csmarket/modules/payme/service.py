"""Payme Merchant API handlers for balance top-ups.

The seven JSON-RPC methods Payme calls — ``CheckPerformTransaction``,
``CreateTransaction``, ``PerformTransaction``, ``CancelTransaction``, ``CheckTransaction``,
``GetStatement``, ``SetFiscalData`` — plus the timeout sweep. Every money move goes through
the ``payments`` hooks (``ensure_attempt``, ``mark_pending``, ``settle``, ``reverse``,
``cancel_pending``); :class:`PaymeTransaction` is only Payme's own state machine. The route
checks Basic auth before anything here runs.

**Lock order (global): top-up → Payme row → payment → user wallet.** ``CheckPerform`` and
``Create`` resolve the top-up with ``lock=True`` before they read or insert the Payme row.
``Perform``, ``Cancel`` and ``SetFiscalData`` start from a Payme id: they read the row
without a lock to learn its account, lock the top-up, then lock the row and re-check its
state. ``CheckTransaction`` and ``GetStatement`` only read and take no lock. The timeout
sweep locks top-ups ``FOR UPDATE SKIP LOCKED`` in its scan, then each row.

A top-up is credited at most once: Create on a paid top-up is −31051; Perform after the
top-up was paid meanwhile (another kassa, or a sibling row sharing this attempt) is −31008
and the transaction is cancelled (state −1, reason 3), so Payme cancels that charge.
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
from csmarket.modules.payme.errors import (
    PaymeError,
    account_busy,
    account_not_found,
    account_not_payable,
    cannot_cancel_spent,
    fiscal_receipt_not_found,
    invalid_amount,
    operation_not_permitted,
    transaction_not_found,
)
from csmarket.modules.payme.models import (
    STATE_CANCELLED,
    STATE_CANCELLED_AFTER_PERFORM,
    STATE_CREATED,
    STATE_PERFORMED,
    PaymeTransaction,
)
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
    reverse,
    settle,
)

log = get_logger("csmarket.payme.service")

PROVIDER = "payme"
#: A state-1 transaction Payme has not performed or cancelled in this long is cancelled.
TIMEOUT = timedelta(hours=12)
#: Payme's cancellation reasons we set ourselves: 3 "execution error" (a second charge
#: refused at perform), 4 "timeout" (the sweep).
REASON_EXECUTION_ERROR = 3
REASON_TIMEOUT = 4

#: A JSON-RPC ``result`` object.
Result = dict[str, Any]

#: Why the payable cannot be paid → the Payme code.
_REFUSALS: dict[str, Callable[[], PaymeError]] = {
    "not_found": account_not_found,
    "paid": account_not_payable,
    "expired": account_not_payable,
    "reversed": account_not_payable,
}

#: Top-up reasons that mean its one credit is already taken.
_CREDITED = ("paid", "reversed")


def now_ms() -> int:
    """The current time as Payme epoch milliseconds."""
    return int(now().timestamp() * 1000)


def _account_number(account: dict[str, Any]) -> str:
    """``account.order`` as sent; −31050 when it is missing, blank or not a string."""
    number = account.get("order")
    if not isinstance(number, str) or not number.strip():
        raise account_not_found()
    return number


def _check_payable(payable: Payable, amount: int) -> None:
    """−31050 unknown, −31051 paid / expired / reversed, −31001 amount ≠ soʻm × 100."""
    if not payable.payable:
        raise _REFUSALS[payable.reason]()
    if amount != int(payable.amount_uzs * 100):
        raise invalid_amount()


async def _txn_by_payme_id(
    db: AsyncSession, payme_id: str, *, lock: bool = False
) -> PaymeTransaction | None:
    stmt = select(PaymeTransaction).where(PaymeTransaction.payme_id == payme_id)
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    return (await db.execute(stmt)).scalar_one_or_none()


async def _lock_txn(db: AsyncSession, txn_id: str) -> PaymeTransaction:
    """Re-read a known Payme row ``FOR UPDATE`` (rows are never deleted)."""
    stmt = (
        select(PaymeTransaction)
        .where(PaymeTransaction.id == txn_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return (await db.execute(stmt)).scalar_one()


async def _locked_by_payme_id(
    db: AsyncSession, payme_id: str, *, missing: Callable[[], PaymeError]
) -> tuple[Payable, PaymeTransaction]:
    """The row named by ``payme_id``, locked in the global order: top-up, then the row.

    Raises:
        PaymeError: ``missing()`` when there is no such row.
    """
    seen = await _txn_by_payme_id(db, payme_id)
    if seen is None:
        raise missing()
    payable = await resolve(db, seen.account, lock=True)
    return payable, await _lock_txn(db, seen.id)


async def _payment(db: AsyncSession, payment_id: str) -> Payment:
    """The attempt, re-read: callers hold its top-up, so its status is the committed one."""
    stmt = select(Payment).where(Payment.id == payment_id).execution_options(populate_existing=True)
    return (await db.execute(stmt)).scalar_one()


def _create_result(txn: PaymeTransaction) -> Result:
    return {"create_time": txn.create_time, "transaction": txn.id, "state": txn.state}


def _replay_create(txn: PaymeTransaction, *, number: str, amount: int) -> Result:
    """Echo a stored transaction — whatever its state now — for a replayed Create.

    Raises:
        PaymeError: −31008 the id belongs to another account; −31001 another amount.
    """
    if txn.account != number:
        raise operation_not_permitted()
    if txn.amount_tiyin != amount:
        raise invalid_amount()
    return _create_result(txn)


async def _release_attempt(db: AsyncSession, txn: PaymeTransaction) -> None:
    """Cancel ``txn``'s attempt unless another state-1 Payme row still holds it.

    ``cancel_pending`` also leaves an attempt a sibling already settled alone.
    """
    sibling = (
        await db.execute(
            select(PaymeTransaction.id)
            .where(
                PaymeTransaction.payment_id == txn.payment_id,
                PaymeTransaction.state == STATE_CREATED,
                PaymeTransaction.id != txn.id,
            )
            .limit(1)
        )
    ).first()
    if sibling is None:
        await cancel_pending(db, payment=await _payment(db, txn.payment_id))


async def _cancel_created(db: AsyncSession, txn: PaymeTransaction, *, reason: int) -> None:
    """State 1 → −1 with ``reason``; the caller holds the top-up and the row."""
    txn.state = STATE_CANCELLED
    txn.reason = reason
    txn.cancel_time = now_ms()
    txn.updated_at = now()
    await db.flush()
    await _release_attempt(db, txn)


async def _refuse_second_charge(db: AsyncSession, txn: PaymeTransaction) -> PaymeError:
    """Cancel ``txn`` (kept: the route commits) and answer −31008 so Payme cancels it."""
    await _cancel_created(db, txn, reason=REASON_EXECUTION_ERROR)
    log.warning(
        "payme.perform.second_charge_refused",
        number=txn.account,
        amount=wire_uzs(Decimal(txn.amount_tiyin) / 100),
    )
    return operation_not_permitted(persist=True)


async def check_perform_transaction(
    db: AsyncSession, *, amount: int, account: dict[str, Any]
) -> Result:
    """``CheckPerformTransaction``: may Payme charge ``amount`` tiyin for this top-up?

    Raises:
        PaymeError: −31050 unknown, −31051 paid / expired / reversed, −31001 amount.
    """
    payable = await resolve(db, _account_number(account), lock=True)
    _check_payable(payable, amount)
    return {"allow": True}


async def create_transaction(
    db: AsyncSession, *, payme_id: str, time: int, amount: int, account: dict[str, Any]
) -> Result:
    """``CreateTransaction``: hold an attempt and register Payme's transaction (state 1).

    Idempotent on ``payme_id``: a replay echoes the stored row whatever its state now (a
    legitimate replay may land after the top-up was paid). A second, different active
    transaction on the same top-up is −31099. The attempt work and the insert share one
    SAVEPOINT, so losing the insert race to another account leaves no attempt ``pending``.

    Args:
        db: Session; the caller commits.
        payme_id: Payme's transaction id (unique).
        time: Payme's creation time (epoch ms), echoed back verbatim.
        amount: Tiyin.
        account: Payme's ``account``; ``order`` is the top-up number.

    Raises:
        PaymeError: −31050 / −31051 / −31001 as ``CheckPerformTransaction``, −31099 busy,
            −31008 the id is another account's.
    """
    number = _account_number(account)
    payable = await resolve(db, number, lock=True)
    seen = await _txn_by_payme_id(db, payme_id)
    if seen is not None:
        # Another account's row is refused from this unlocked read: its top-up is not the one
        # we hold, so locking the row here would step outside the global lock order.
        if seen.account != number:
            raise operation_not_permitted()
        return _replay_create(await _lock_txn(db, seen.id), number=number, amount=amount)
    _check_payable(payable, amount)
    busy = (
        await db.execute(
            select(PaymeTransaction.id)
            .where(
                PaymeTransaction.account == payable.number,
                PaymeTransaction.state == STATE_CREATED,
                PaymeTransaction.payme_id != payme_id,
            )
            .limit(1)
        )
    ).first()
    if busy is not None:
        raise account_busy()
    try:
        async with db.begin_nested():
            try:
                payment = await ensure_attempt(db, payable=payable, provider=PROVIDER)
            except AlreadyPaidError:  # pragma: no cover - refused above under the same lock
                raise account_not_payable() from None
            await mark_pending(db, payment=payment)
            txn = PaymeTransaction(
                payme_id=payme_id,
                payment_id=payment.id,
                account=payable.number,
                amount_tiyin=amount,
                state=STATE_CREATED,
                create_time=time,
            )
            db.add(txn)
            await db.flush()
    except IntegrityError:
        # The same payme_id for another account locked another top-up and won the insert.
        winner = await _txn_by_payme_id(db, payme_id)
        if winner is None:  # pragma: no cover - the unique id collided, so the row exists
            raise
        return _replay_create(winner, number=number, amount=amount)
    log.info("payme.created", number=payable.number, amount=wire_uzs(payable.amount_uzs))
    return _create_result(txn)


async def perform_transaction(db: AsyncSession, *, payme_id: str) -> Result:
    """``PerformTransaction``: Payme debited the customer — settle, credit the top-up once.

    A replay on a performed transaction echoes it. If the top-up was credited meanwhile
    (another kassa, or a sibling Payme row on this attempt), this charge is refused with
    −31008 and the transaction is cancelled (−1, reason 3) — ``persist`` is set so the
    route commits that.

    Raises:
        PaymeError: −31003 unknown, −31008 cancelled or a second charge.
    """
    payable, txn = await _locked_by_payme_id(db, payme_id, missing=transaction_not_found)
    if txn.state == STATE_PERFORMED:
        return {"transaction": txn.id, "perform_time": txn.perform_time, "state": txn.state}
    if txn.state != STATE_CREATED:
        raise operation_not_permitted()
    payment = await _payment(db, txn.payment_id)
    if payable.reason in _CREDITED or payment.status == "succeeded":
        raise await _refuse_second_charge(db, txn)
    try:
        await settle(db, payment=payment, event_id=f"payme:{payme_id}")
    except AlreadyPaidError:  # pragma: no cover - refused above under the same top-up lock
        raise await _refuse_second_charge(db, txn) from None
    txn.state = STATE_PERFORMED
    txn.perform_time = now_ms()
    txn.updated_at = now()
    await db.flush()
    log.info("payme.performed", number=txn.account, amount=wire_uzs(payable.amount_uzs))
    return {"transaction": txn.id, "perform_time": txn.perform_time, "state": txn.state}


async def cancel_transaction(db: AsyncSession, *, payme_id: str, reason: int) -> Result:
    """``CancelTransaction``, routed by the transaction's state.

    State 1 → −1: the attempt is released (unless another state-1 row holds it). State 2
    → −2: the top-up is reversed if its money is still on the balance; otherwise −31007
    and nothing changes (ruling R7). A replay on a cancelled transaction echoes it.

    Raises:
        PaymeError: −31003 unknown, −31007 the top-up was spent.
    """
    _, txn = await _locked_by_payme_id(db, payme_id, missing=transaction_not_found)
    if txn.state == STATE_CREATED:
        await _cancel_created(db, txn, reason=reason)
    elif txn.state == STATE_PERFORMED:
        try:
            await reverse(
                db, payment=await _payment(db, txn.payment_id), event_id=f"payme:{payme_id}"
            )
        except TopupSpentError:
            raise cannot_cancel_spent() from None
        txn.state = STATE_CANCELLED_AFTER_PERFORM
        txn.reason = reason
        txn.cancel_time = now_ms()
        txn.updated_at = now()
        await db.flush()
    log.info("payme.cancelled", number=txn.account, state=txn.state, reason=txn.reason)
    return {"transaction": txn.id, "cancel_time": txn.cancel_time, "state": txn.state}


async def check_transaction(db: AsyncSession, *, payme_id: str) -> Result:
    """``CheckTransaction``: the transaction's times, state and reason (a plain read).

    Raises:
        PaymeError: −31003 unknown.
    """
    txn = await _txn_by_payme_id(db, payme_id)
    if txn is None:
        raise transaction_not_found()
    return {
        "create_time": txn.create_time,
        "perform_time": txn.perform_time,
        "cancel_time": txn.cancel_time,
        "transaction": txn.id,
        "state": txn.state,
        "reason": txn.reason,
    }


async def get_statement(db: AsyncSession, *, from_ms: int, to_ms: int) -> Result:
    """``GetStatement``: transactions Payme created in ``[from_ms, to_ms]``, oldest first."""
    rows = (
        await db.execute(
            select(PaymeTransaction)
            .where(PaymeTransaction.create_time >= from_ms, PaymeTransaction.create_time <= to_ms)
            .order_by(PaymeTransaction.create_time, PaymeTransaction.id)
        )
    ).scalars()
    return {
        "transactions": [
            {
                "id": row.payme_id,
                "time": row.create_time,
                "amount": row.amount_tiyin,
                "account": {"order": row.account},
                "create_time": row.create_time,
                "perform_time": row.perform_time,
                "cancel_time": row.cancel_time,
                "transaction": row.id,
                "state": row.state,
                "reason": row.reason,
                "receivers": [],
            }
            for row in rows
        ]
    }


async def set_fiscal_data(
    db: AsyncSession, *, payme_id: str, type_: str, fiscal_data: dict[str, Any]
) -> Result:
    """``SetFiscalData``: keep Payme's receipt under its ``type`` (``PERFORM`` / ``CANCEL``).

    Raises:
        PaymeError: −32001 unknown transaction.
    """
    _, txn = await _locked_by_payme_id(db, payme_id, missing=fiscal_receipt_not_found)
    # Reassign, not mutate, so SQLAlchemy sees the JSONB column change.
    txn.fiscal_data = {**txn.fiscal_data, type_: fiscal_data}
    txn.updated_at = now()
    await db.flush()
    return {"success": True}


async def cancel_stale(db: AsyncSession, *, limit: int = 500) -> int:
    """Cancel state-1 transactions Payme left untouched for :data:`TIMEOUT` (−1, reason 4).

    The scan locks the rows' top-ups ``FOR UPDATE SKIP LOCKED`` (one a callback holds is
    left for the next tick), then each row is re-read ``FOR UPDATE`` and re-checked: a
    ``PerformTransaction`` that landed meanwhile is never clobbered. Each row runs in its
    own savepoint, so one failure does not stop the rest. Flushes, never commits.

    Returns:
        How many transactions went to state −1.
    """
    cutoff = now_ms() - int(TIMEOUT.total_seconds() * 1000)
    stmt = (
        select(PaymeTransaction.id)
        .join(Payment, Payment.id == PaymeTransaction.payment_id)
        .join(WalletTopup, WalletTopup.id == Payment.topup_id)
        .where(PaymeTransaction.state == STATE_CREATED, PaymeTransaction.create_time < cutoff)
        .order_by(PaymeTransaction.create_time)
        .limit(limit)
        .with_for_update(of=WalletTopup, skip_locked=True)
    )
    cancelled = 0
    for txn_id in list((await db.execute(stmt)).scalars()):
        try:
            async with db.begin_nested():
                txn = await _lock_txn(db, txn_id)
                if txn.state != STATE_CREATED:
                    continue
                await _cancel_created(db, txn, reason=REASON_TIMEOUT)
        except Exception:  # one bad row must not stop the sweep
            log.exception("payme.timeout.row_failed", payme_txn_id=txn_id)
            continue
        cancelled += 1
    return cancelled


__all__ = [
    "PROVIDER",
    "REASON_EXECUTION_ERROR",
    "REASON_TIMEOUT",
    "TIMEOUT",
    "Result",
    "cancel_stale",
    "cancel_transaction",
    "check_perform_transaction",
    "check_transaction",
    "create_transaction",
    "get_statement",
    "now_ms",
    "perform_transaction",
    "set_fiscal_data",
]
