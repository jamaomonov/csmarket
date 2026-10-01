"""Provider hooks (ruling R6) — every kassa calls these; nothing else moves money state.

:func:`ensure_attempt` opens (or reuses) an attempt; :func:`mark_pending`,
:func:`settle`, :func:`reverse` and :func:`cancel_pending` move it. Each takes the
session-attached payment and re-reads it ``FOR UPDATE``: one payable can have sibling
attempts, and a timeout sweep and a late callback must not both see ``pending``.

An attempt pays its *owner*: a top-up (M3) or an order (M4a). Settling a top-up credits
the balance; settling an order marks it ``paid`` and wakes the worker (``NOTIFY orders``)
— the skin is bought at once, so a kassa can never reverse an order (ruling R7).

**Lock order, everywhere: the owner (top-up or order), then the payment, then the user's
wallet.** A kassa opening an attempt resolves the owner with ``lock=True`` before it touches
the attempt (``ensure_attempt`` → ``mark_pending``), so every hook that moves an attempt —
:func:`mark_pending`, :func:`settle`, :func:`reverse`, :func:`cancel_pending` — takes the
owner first too, whatever else the caller locked in the same transaction; the other order
would let a create and a settle on the same owner deadlock. A kassa's own transaction row
sits between the two (owner → kassa row → payment → user wallet).

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
from csmarket.modules.orders.api import Order, mark_paid
from csmarket.modules.payments.external_ids import unclaimed_external_id
from csmarket.modules.payments.fsm import LIVE, InvalidTransitionError, move
from csmarket.modules.payments.models import Payment, WalletTopup
from csmarket.modules.payments.payable import Payable
from csmarket.modules.wallet.api import InsufficientBalanceError, credit_topup, reverse_topup

log = get_logger("csmarket.payments.hooks")

#: Top-up statuses that already consumed their one credit.
_CREDITED = frozenset({"succeeded", "reversed"})


#: An attempt's owner: what it pays for.
Owner = WalletTopup | Order


class AlreadyPaidError(ConflictError):
    """The owner was already paid through another attempt (a top-up credited, an order past
    ``pending``); refuse this charge."""

    type_uri = "https://csmarket.uz/errors/already-paid"
    title = "Already paid"


class ReversalRefusedError(ConflictError):
    """A kassa asks to reverse a succeeded payment we will not give back (ruling R7).

    Kassas catch this one type: Payme answers −31007, Uzum 10017.
    """

    type_uri = "https://csmarket.uz/errors/reversal-refused"
    title = "Reversal refused"


class TopupSpentError(ReversalRefusedError):
    """The kassa asks to reverse a top-up whose money is no longer on the balance."""

    type_uri = "https://csmarket.uz/errors/topup-spent"
    title = "Top-up already spent"


class OrderReversalRefusedError(ReversalRefusedError):
    """The kassa asks to reverse an order payment: the skin is bought at payment and refunds
    go to the balance, so a kassa never takes an order's money back."""

    type_uri = "https://csmarket.uz/errors/order-reversal-refused"
    title = "Order payments cannot be reversed"


def _payment_id(payment: Payment) -> str:
    """The row's primary key, read from its identity (safe on an expired instance)."""
    identity = sa_inspect(payment).identity
    if identity is None:
        raise ValueError("payment is not persistent")
    return str(identity[0])


async def _owner_ref(
    db: AsyncSession, payment_id: str
) -> tuple[type[WalletTopup] | type[Order], str | None]:
    """The owner's model and id of attempt ``payment_id`` (an unlocked read).

    The ``purpose`` checks guarantee the id is set; a missing one finds no row.
    """
    purpose, topup_id, order_id = (
        await db.execute(
            select(Payment.purpose, Payment.topup_id, Payment.order_id).where(
                Payment.id == payment_id
            )
        )
    ).one()
    if purpose == "order":
        return Order, order_id
    return WalletTopup, topup_id


async def _lock_owner_then_payment(db: AsyncSession, payment: Payment) -> Owner:
    """Lock the attempt's owner (its top-up or its order), then the attempt itself; both
    re-read from the DB."""
    model, owner_id = await _owner_ref(db, _payment_id(payment))
    owner: Owner
    if model is Order:
        owner = (
            await db.execute(
                select(Order)
                .where(Order.id == owner_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one()
    else:
        owner = (
            await db.execute(
                select(WalletTopup)
                .where(WalletTopup.id == owner_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one()
    await db.refresh(payment, with_for_update=True)
    return owner


async def lock_owner_or_skip(db: AsyncSession, *, payment_id: str) -> bool:
    """Lock the owner of attempt ``payment_id`` ``FOR UPDATE SKIP LOCKED`` (timeout sweeps).

    Returns:
        ``False`` when another transaction holds the owner (a callback in flight): the
        sweep leaves that row for its next tick.
    """
    model, owner_id = await _owner_ref(db, payment_id)
    stmt = select(model.id).where(model.id == owner_id).with_for_update(skip_locked=True)
    return (await db.execute(stmt)).scalar_one_or_none() is not None


def _owner_of(payable: Payable) -> Owner:
    """The top-up or order ``payable`` resolved to.

    Raises:
        ValueError: ``payable`` is ``not_found`` — there is nothing to pay.
    """
    owner: Owner | None = payable.order if payable.kind == "order" else payable.topup
    if owner is None:
        raise ValueError(f"nothing to pay: {payable.reason}")
    return owner


async def ensure_attempt(db: AsyncSession, *, payable: Payable, provider: str) -> Payment:
    """The owner's live (``created``/``pending``) attempt of ``provider``, or a new one.

    The owner is the top-up or the order ``payable`` resolved to; a new attempt carries its
    number, user and amount (``amount_uzs`` / ``price_uzs``) and starts ``created`` with
    ``provider_ref = <provider>:<number>`` — suffixed with its id when an earlier attempt of
    the provider holds that reference (a declined card retried in the same kassa). The
    caller resolved ``payable`` with ``lock=True``, so two concurrent calls for one owner
    serialise on its row. Payability is the caller's check for an expired owner (a kassa
    asking about one answers "cannot be paid"); an owner that was already paid is refused
    here, so no new attempt is ever opened on it.

    Raises:
        AlreadyPaidError: the top-up is ``paid`` or ``reversed``; the order is past
            ``pending`` (``paid``, ``buying``, …).
        ValueError: ``payable`` is ``not_found``.
    """
    owner = _owner_of(payable)
    if payable.reason in ("paid", "reversed"):
        log.warning(
            "payments.order.second_payment_refused"
            if payable.kind == "order"
            else "payments.topup.second_payment_refused",
            number=payable.number,
            provider=provider,
        )
        raise AlreadyPaidError(f"{payable.kind} already paid")
    owned_by = (
        Payment.order_id == owner.id if isinstance(owner, Order) else Payment.topup_id == owner.id
    )
    live_stmt = (
        select(Payment)
        .where(owned_by, Payment.provider == provider, Payment.status.in_(LIVE))
        .order_by(Payment.created_at.desc())
        .limit(1)
    )
    live = (await db.execute(live_stmt)).scalar_one_or_none()
    if live is not None:
        return live
    payment_id = new_id()
    ref = await unclaimed_external_id(
        db, provider=provider, external_id=f"{provider}:{owner.number}", payment_id=payment_id
    )
    payment = Payment(
        id=payment_id,
        number=owner.number,
        purpose=payable.kind,
        topup_id=owner.id if isinstance(owner, WalletTopup) else None,
        order_id=owner.id if isinstance(owner, Order) else None,
        user_id=owner.user_id,
        provider=provider,
        provider_ref=ref,
        amount_uzs=owner.price_uzs if isinstance(owner, Order) else owner.amount_uzs,
        status="created",
    )
    db.add(payment)
    await db.flush()
    log.info("payments.attempt.created", number=owner.number, provider=provider)
    return payment


async def mark_pending(db: AsyncSession, *, payment: Payment) -> None:
    """The kassa now holds a transaction for ``payment``: ``created`` → ``pending``.

    A no-op when already ``pending``. Locks the owner, then the attempt.

    Raises:
        InvalidTransitionError: the attempt is already settled, failed or cancelled.
    """
    await _lock_owner_then_payment(db, payment)
    if payment.status == "pending":
        return
    move(payment, "pending")
    await db.flush()


async def settle(db: AsyncSession, *, payment: Payment, event_id: str) -> None:
    """Money arrived for ``payment``: mark it succeeded and pay its owner once.

    A top-up is credited to the balance; an order goes ``paid`` (``orders.mark_paid``:
    ``paid_with`` = the provider, ``NOTIFY orders`` on commit). A no-op when this attempt
    already succeeded (a retried callback — no second credit, no second ``NOTIFY``). Pays
    even when the owner's ``expires_at`` has passed — the kassa held the attempt and the
    money arrived. ``event_id`` (the kassa's transaction id) is kept in the attempt's
    metadata.

    Raises:
        AlreadyPaidError: the top-up was already credited, or the order is no longer
            ``pending`` (paid through another attempt, or cancelled); the kassa refuses
            this second charge.
        InvalidTransitionError: the attempt is cancelled, failed or refunded.
    """
    owner = await _lock_owner_then_payment(db, payment)
    if payment.status == "succeeded":
        return
    if isinstance(owner, Order):
        await _settle_order(db, payment=payment, order=owner, event_id=event_id)
        return
    if owner.status in _CREDITED:
        log.warning(
            "payments.topup.second_payment_refused", number=owner.number, provider=payment.provider
        )
        raise AlreadyPaidError("top-up already paid")
    move(payment, "succeeded")
    payment.extra_metadata = {**payment.extra_metadata, "settle_event_id": event_id}
    owner.status = "succeeded"
    owner.payment_id = payment.id
    owner.succeeded_at = payment.succeeded_at
    await credit_topup(
        db,
        user_id=owner.user_id,
        topup_id=owner.id,
        amount=owner.amount_uzs,
        provider=payment.provider,
    )
    await db.flush()
    log.info(
        "payments.topup.credited",
        number=owner.number,
        provider=payment.provider,
        amount=str(owner.amount_uzs),
    )


async def _settle_order(db: AsyncSession, *, payment: Payment, order: Order, event_id: str) -> None:
    """The order half of :func:`settle`; the caller holds the order, then the attempt."""
    if order.status != "pending":
        log.warning(
            "payments.order.second_payment_refused",
            number=order.number,
            provider=payment.provider,
            status=order.status,
        )
        raise AlreadyPaidError("order already paid")
    move(payment, "succeeded")
    payment.extra_metadata = {**payment.extra_metadata, "settle_event_id": event_id}
    await mark_paid(db, order, provider=payment.provider)
    log.info(
        "payments.order.paid",
        number=order.number,
        provider=payment.provider,
        amount=str(payment.amount_uzs),
    )


async def reverse(db: AsyncSession, *, payment: Payment, event_id: str) -> None:
    """The kassa reverses a succeeded ``payment``: claw a top-up back if it is unspent.

    A no-op when already ``refunded``. Otherwise the user's wallet is locked and debited
    (``topup_reversal``), the attempt goes ``refunded`` and the top-up ``reversed``. An
    order payment is never reversed (ruling R7).

    Raises:
        TopupSpentError: the balance no longer covers the top-up (ruling R7); nothing is
            written and the caller rolls back.
        OrderReversalRefusedError: ``payment`` paid an order; nothing is written.
        InvalidTransitionError: the attempt never succeeded.
    """
    owner = await _lock_owner_then_payment(db, payment)
    if isinstance(owner, Order):
        log.warning(
            "payments.order.reverse_refused", number=owner.number, provider=payment.provider
        )
        raise OrderReversalRefusedError("an order payment is never reversed by a kassa")
    if payment.status == "refunded":
        return
    if payment.status != "succeeded":
        raise InvalidTransitionError(f"payment cannot go {payment.status} -> refunded")
    try:
        await reverse_topup(
            db,
            user_id=owner.user_id,
            topup_id=owner.id,
            amount=owner.amount_uzs,
            provider=payment.provider,
        )
    except InsufficientBalanceError as exc:
        log.warning(
            "payments.topup.reverse_refused", number=owner.number, amount=str(owner.amount_uzs)
        )
        raise TopupSpentError("the top-up was already spent") from exc
    move(payment, "refunded")
    payment.extra_metadata = {**payment.extra_metadata, "reverse_event_id": event_id}
    owner.status = "reversed"
    await db.flush()
    log.info(
        "payments.topup.reversed",
        number=owner.number,
        provider=payment.provider,
        amount=str(owner.amount_uzs),
    )


async def cancel_pending(db: AsyncSession, *, payment: Payment) -> None:
    """The kassa dropped ``payment`` before money moved: ``created``/``pending`` → ``cancelled``.

    A no-op on any other status — an attempt a sibling already settled is never pulled
    back to ``cancelled`` without a reversal. Locks the owner, then the attempt. An order
    stays ``pending`` (its own expiry sweep cancels it).
    """
    await _lock_owner_then_payment(db, payment)
    if payment.status not in LIVE:
        return
    move(payment, "cancelled")
    await db.flush()


__all__ = [
    "AlreadyPaidError",
    "OrderReversalRefusedError",
    "Owner",
    "ReversalRefusedError",
    "TopupSpentError",
    "cancel_pending",
    "ensure_attempt",
    "lock_owner_or_skip",
    "mark_pending",
    "reverse",
    "settle",
]
