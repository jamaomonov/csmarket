"""Pay an order: from the balance in one transaction (ruling R8) or through a kassa.

:func:`pay_order` serves ``POST /orders/{number}/pay``; :func:`dev_pay` the dev-only mock pay
route. Both lock the order first (``payments.resolve(lock=True)``) — lock order everywhere:
the order, then a kassa's row, then the payment, then the user's wallet.

- **The balance** (``provider="wallet"``): the wallet is locked and debited
  (``wallet.debit_purchase``), a ``payments`` row ``provider="wallet"`` is written
  ``succeeded``, the order goes ``paid`` and ``NOTIFY orders`` wakes the worker — all in
  one transaction. A short balance is 409 ``balance_too_low`` and changes nothing. No
  mixed payment.
- **A kassa**: the order's live attempt in that kassa is opened or reused and the kassa's
  payment page is returned; the order goes ``paid`` when the kassa settles
  (``payments.hooks.settle``).

The ``Idempotency-Key`` is kept in the replay store under ``orders.pay:{number}`` with the
request it answered: the same key and body replay the stored answer; the same key with
another body is 409 ``idempotency_mismatch``. The replay is looked up with the order
locked, so a double-click's second request waits for the first and replays it.

This module imports ``payments``: ``orders.api`` never exports it (ruling A).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.errors import ConflictError, NotFoundError, ValidationError
from csmarket.core.idempotency import load_replay, save_replay
from csmarket.core.ids import new_id
from csmarket.core.logging import get_logger
from csmarket.core.numbers import is_number, is_topup_number
from csmarket.modules.orders.models import Order
from csmarket.modules.orders.paid import mark_paid
from csmarket.modules.orders.schemas import OrderOut, OrderPayOut
from csmarket.modules.orders.service import get_owned, order_out
from csmarket.modules.payments.api import (
    Payable,
    Payment,
    available_providers,
    ensure_attempt,
    get_gateway,
    mark_pending,
    resolve,
    settle,
)
from csmarket.modules.payments.api import move as move_payment
from csmarket.modules.wallet.api import WALLET, debit_purchase

log = get_logger("csmarket.orders.paying")


def _scope(number: str) -> str:
    """The replay store's scope of order ``number``'s pay calls."""
    return f"orders.pay:{number}"


async def _locked_own(db: AsyncSession, *, user_id: str, number: str) -> tuple[Payable, Order]:
    """Order ``number`` resolved and locked ``FOR UPDATE``, and the order row.

    Raises:
        NotFoundError: malformed, a top-up's, unknown, or another user's order.
    """
    if not is_number(number) or is_topup_number(number):
        raise NotFoundError("order not found")
    payable = await resolve(db, number, lock=True)
    if payable.order is None or payable.user_id != user_id:
        raise NotFoundError("order not found")
    return payable, payable.order


def _refuse_unless_payable(payable: Payable) -> None:
    """409 ``order_not_payable`` with ``reason`` ``paid`` or ``expired`` (also cancelled)."""
    if not payable.payable:
        raise ConflictError(
            "this order cannot be paid", code="order_not_payable", reason=payable.reason
        )


async def _replayed(
    db: AsyncSession, *, number: str, key: str, request: dict[str, Any]
) -> OrderPayOut | None:
    """The stored answer for ``key`` when it answered this very request.

    Raises:
        ConflictError: ``code="idempotency_mismatch"`` — the key answered another body.
    """
    hit = await load_replay(db, scope=_scope(number), idempotency_key=key)
    if hit is None:
        return None
    stored = hit.body or {}
    if stored.get("request") != request:
        raise ConflictError(
            "this Idempotency-Key was used for another request", code="idempotency_mismatch"
        )
    return OrderPayOut.model_validate(stored["response"])


async def _owner_view(db: AsyncSession, *, user_id: str, number: str) -> OrderOut:
    """The owner's view of the order as it stands in this transaction."""
    row = await get_owned(db, user_id, number)
    if row is None:  # pragma: no cover -- the order is locked and theirs; never seen
        raise NotFoundError("order not found")
    return order_out(row.order, row.trade, row.image_url)


async def _pay_from_balance(db: AsyncSession, order: Order) -> None:
    """Ruling R8 on the locked ``order``: debit, a succeeded ``wallet`` payment, ``paid``."""
    await debit_purchase(db, user_id=order.user_id, order_id=order.id, amount=order.price_uzs)
    payment = Payment(
        id=new_id(),
        number=order.number,
        purpose="order",
        order_id=order.id,
        user_id=order.user_id,
        provider=WALLET,
        provider_ref=f"{WALLET}:{order.number}",
        amount_uzs=order.price_uzs,
        status="created",
    )
    move_payment(payment, "succeeded")
    db.add(payment)
    await db.flush()
    await mark_paid(db, order, provider=WALLET)
    log.info("orders.paid", number=order.number, provider=WALLET, amount=str(order.price_uzs))


async def _open_in_kassa(db: AsyncSession, payable: Payable, *, provider: str, locale: str) -> str:
    """Open (or reuse) the order's attempt in ``provider``; the kassa's payment page.

    Raises:
        ValidationError: ``code="order_provider"`` — the kassa is not available here.
    """
    if provider not in available_providers():
        raise ValidationError("payment provider not available", code="order_provider")
    await ensure_attempt(db, payable=payable, provider=provider)
    return get_gateway(provider).intent_url(payable=payable, locale=locale)


async def pay_order(
    db: AsyncSession,
    *,
    user_id: str,
    number: str,
    provider: str,
    locale: str,
    idempotency_key: str,
) -> OrderPayOut:
    """Pay ``user_id``'s order ``number`` from the balance or open it in a kassa; commits.

    Args:
        db: Session; committed here (the payment, the replay row and ``NOTIFY`` together).
        user_id: The signed-in buyer.
        number: The order's number.
        provider: ``wallet`` or a kassa slug (``click``, ``payme``, ``uzum``, ``mock``).
        locale: ``ru``, ``uz`` or ``en`` — the kassa's page and the page returned to.
        idempotency_key: The request's ``Idempotency-Key`` (16..160 chars).

    Returns:
        The order as it stands and, for a kassa, its payment page (``None`` for the balance).

    Raises:
        NotFoundError: not the buyer's order (or not an order number).
        ConflictError: ``order_not_payable`` (+ ``reason`` ``paid`` | ``expired``),
            ``idempotency_mismatch``.
        InsufficientBalanceError: ``code="balance_too_low"``; nothing is written.
        ValidationError: ``code="order_provider"`` — the kassa is not available here.
    """
    payable, order = await _locked_own(db, user_id=user_id, number=number)
    request: dict[str, Any] = {"provider": provider, "locale": locale}
    replay = await _replayed(db, number=number, key=idempotency_key, request=request)
    if replay is not None:
        await db.commit()
        return replay
    _refuse_unless_payable(payable)
    intent_url: str | None = None
    if provider == WALLET:
        await _pay_from_balance(db, order)
    else:
        intent_url = await _open_in_kassa(db, payable, provider=provider, locale=locale)
    out = OrderPayOut(
        order=await _owner_view(db, user_id=user_id, number=number), intent_url=intent_url
    )
    await save_replay(
        db,
        scope=_scope(number),
        idempotency_key=idempotency_key,
        body={"request": request, "response": out.model_dump(mode="json")},
    )
    await db.commit()
    return out


async def dev_pay(db: AsyncSession, *, user_id: str, number: str) -> OrderOut:
    """Dev only: pay ``user_id``'s order ``number`` through ``mock`` (the real hooks); commits.

    ``ensure_attempt("mock")`` → ``mark_pending`` → ``settle(event_id="mock:<attempt id>")``.
    A no-op once the order is paid. The caller checked the dev gate.

    Raises:
        NotFoundError: not the buyer's order.
        ConflictError: ``order_not_payable`` with ``reason="expired"``.
    """
    payable, _ = await _locked_own(db, user_id=user_id, number=number)
    if payable.reason != "paid":
        _refuse_unless_payable(payable)
        attempt = await ensure_attempt(db, payable=payable, provider="mock")
        await mark_pending(db, payment=attempt)
        await settle(db, payment=attempt, event_id=f"mock:{attempt.id}")
    out = await _owner_view(db, user_id=user_id, number=number)
    await db.commit()
    return out


__all__ = ["dev_pay", "pay_order"]
