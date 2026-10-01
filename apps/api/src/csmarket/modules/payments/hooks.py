"""Provider hooks (ruling R6) — every kassa calls these; nothing else moves money state.

:func:`ensure_attempt` opens (or reuses) an attempt; :func:`mark_pending`,
:func:`settle`, :func:`reverse` and :func:`cancel_pending` move it. Each takes the
session-attached payment and re-reads it ``FOR UPDATE``: one top-up can have sibling
attempts, and a timeout sweep and a late callback must not both see ``pending``.

**Lock order, everywhere: the top-up, then the payment, then the user's wallet.** A kassa
opening an attempt resolves the top-up with ``lock=True`` before it touches the attempt
(``ensure_attempt`` → ``mark_pending``), so :func:`settle` and :func:`reverse` take the
top-up first too; the other order would let a create and a settle on the same top-up
deadlock. ``mark_pending`` and ``cancel_pending`` lock only the payment.

The caller commits; the hooks only flush. Log lines carry the number, provider and amount,
never the user.
"""

from __future__ import annotations

from sqlalchemy import inspect as sa_inspect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.errors import ConflictError
from csmarket.core.ids import new_id
from csmarket.core.logging import get_logger
from csmarket.modules.payments.external_ids import unclaimed_external_id
from csmarket.modules.payments.fsm import LIVE, InvalidTransitionError, move
from csmarket.modules.payments.models import Payment, WalletTopup
from csmarket.modules.payments.payable import Payable
from csmarket.modules.wallet.api import InsufficientBalanceError, credit_topup, reverse_topup

log = get_logger("csmarket.payments.hooks")

#: Top-up statuses that already consumed their one credit.
_CREDITED = frozenset({"succeeded", "reversed"})


class AlreadyPaidError(ConflictError):
    """The top-up was already credited through another attempt; refuse this charge."""

    type_uri = "https://csmarket.uz/errors/already-paid"
    title = "Already paid"


class TopupSpentError(ConflictError):
    """The kassa asks to reverse a top-up whose money is no longer on the balance."""

    type_uri = "https://csmarket.uz/errors/topup-spent"
    title = "Top-up already spent"


def _payment_id(payment: Payment) -> str:
    """The row's primary key, read from its identity (safe on an expired instance)."""
    identity = sa_inspect(payment).identity
    if identity is None:
        raise ValueError("payment is not persistent")
    return str(identity[0])


async def _lock_topup_then_payment(db: AsyncSession, payment: Payment) -> WalletTopup:
    """Lock the attempt's top-up, then the attempt itself; both re-read from the DB.

    Raises:
        NotImplementedError: an order payment (orders are paid from M4).
    """
    purpose, topup_id = (
        await db.execute(
            select(Payment.purpose, Payment.topup_id).where(Payment.id == _payment_id(payment))
        )
    ).one()
    if purpose != "topup" or topup_id is None:
        raise NotImplementedError("orders are paid from M4")
    stmt = (
        select(WalletTopup)
        .where(WalletTopup.id == topup_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    topup = (await db.execute(stmt)).scalar_one()
    await db.refresh(payment, with_for_update=True)
    return topup


async def ensure_attempt(db: AsyncSession, *, payable: Payable, provider: str) -> Payment:
    """The top-up's live (``created``/``pending``) attempt of ``provider``, or a new one.

    A new attempt starts ``created`` with ``provider_ref = <provider>:<number>`` — suffixed
    with its id when an earlier attempt of the provider holds that reference (a declined
    card retried in the same kassa). The caller resolved ``payable`` with ``lock=True``, so
    two concurrent calls for one top-up serialise on its row. Payability is the caller's
    check: the expiry sweep, for one, opens nothing but reads expired top-ups' attempts.

    Raises:
        NotImplementedError: ``payable`` is not a top-up (orders arrive in M4).
    """
    topup = payable.topup
    if payable.kind != "topup" or topup is None:
        raise NotImplementedError("orders are paid from M4")
    live_stmt = (
        select(Payment)
        .where(
            Payment.topup_id == topup.id,
            Payment.provider == provider,
            Payment.status.in_(LIVE),
        )
        .order_by(Payment.created_at.desc())
        .limit(1)
    )
    live = (await db.execute(live_stmt)).scalar_one_or_none()
    if live is not None:
        return live
    payment_id = new_id()
    ref = await unclaimed_external_id(
        db, provider=provider, external_id=f"{provider}:{topup.number}", payment_id=payment_id
    )
    payment = Payment(
        id=payment_id,
        number=topup.number,
        purpose="topup",
        topup_id=topup.id,
        user_id=topup.user_id,
        provider=provider,
        provider_ref=ref,
        amount_uzs=topup.amount_uzs,
        status="created",
    )
    db.add(payment)
    await db.flush()
    log.info("payments.attempt.created", number=topup.number, provider=provider)
    return payment


async def mark_pending(db: AsyncSession, *, payment: Payment) -> None:
    """The kassa now holds a transaction for ``payment``: ``created`` → ``pending``.

    A no-op when already ``pending``.

    Raises:
        InvalidTransitionError: the attempt is already settled, failed or cancelled.
    """
    await db.refresh(payment, with_for_update=True)
    if payment.status == "pending":
        return
    move(payment, "pending")
    await db.flush()


async def settle(db: AsyncSession, *, payment: Payment, event_id: str) -> None:
    """Money arrived for ``payment``: mark it succeeded and credit its top-up once.

    A no-op when this attempt already succeeded (a retried callback). Credits even when
    the top-up's ``expires_at`` has passed — the kassa held the attempt and the money
    arrived. ``event_id`` (the kassa's transaction id) is kept in the attempt's metadata.

    Raises:
        AlreadyPaidError: the top-up was already credited through another attempt; the
            kassa refuses this second charge.
        InvalidTransitionError: the attempt is cancelled, failed or refunded.
        NotImplementedError: an order payment (M4).
    """
    topup = await _lock_topup_then_payment(db, payment)
    if payment.status == "succeeded":
        return
    if topup.status in _CREDITED:
        log.warning(
            "payments.topup.second_payment_refused", number=topup.number, provider=payment.provider
        )
        raise AlreadyPaidError("top-up already paid")
    move(payment, "succeeded")
    payment.extra_metadata = {**payment.extra_metadata, "settle_event_id": event_id}
    topup.status = "succeeded"
    topup.payment_id = payment.id
    topup.succeeded_at = payment.succeeded_at
    await credit_topup(
        db,
        user_id=topup.user_id,
        topup_id=topup.id,
        amount=topup.amount_uzs,
        provider=payment.provider,
    )
    await db.flush()
    log.info(
        "payments.topup.credited",
        number=topup.number,
        provider=payment.provider,
        amount=str(topup.amount_uzs),
    )


async def reverse(db: AsyncSession, *, payment: Payment, event_id: str) -> None:
    """The kassa reverses a succeeded ``payment``: claw the top-up back if it is unspent.

    A no-op when already ``refunded``. Otherwise the user's wallet is locked and debited
    (``topup_reversal``), the attempt goes ``refunded`` and the top-up ``reversed``.

    Raises:
        TopupSpentError: the balance no longer covers the top-up (ruling R7); nothing is
            written and the caller rolls back.
        InvalidTransitionError: the attempt never succeeded.
        NotImplementedError: an order payment (M4).
    """
    topup = await _lock_topup_then_payment(db, payment)
    if payment.status == "refunded":
        return
    if payment.status != "succeeded":
        raise InvalidTransitionError(f"payment cannot go {payment.status} -> refunded")
    try:
        await reverse_topup(
            db,
            user_id=topup.user_id,
            topup_id=topup.id,
            amount=topup.amount_uzs,
            provider=payment.provider,
        )
    except InsufficientBalanceError as exc:
        log.warning(
            "payments.topup.reverse_refused", number=topup.number, amount=str(topup.amount_uzs)
        )
        raise TopupSpentError("the top-up was already spent") from exc
    move(payment, "refunded")
    payment.extra_metadata = {**payment.extra_metadata, "reverse_event_id": event_id}
    topup.status = "reversed"
    await db.flush()
    log.info(
        "payments.topup.reversed",
        number=topup.number,
        provider=payment.provider,
        amount=str(topup.amount_uzs),
    )


async def cancel_pending(db: AsyncSession, *, payment: Payment) -> None:
    """The kassa dropped ``payment`` before money moved: ``created``/``pending`` → ``cancelled``.

    A no-op on any other status — an attempt a sibling already settled is never pulled
    back to ``cancelled`` without a reversal.
    """
    await db.refresh(payment, with_for_update=True)
    if payment.status not in LIVE:
        return
    move(payment, "cancelled")
    await db.flush()


__all__ = [
    "AlreadyPaidError",
    "TopupSpentError",
    "cancel_pending",
    "ensure_attempt",
    "mark_pending",
    "reverse",
    "settle",
]
