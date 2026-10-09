"""An order on the ledger: paid from the balance once, refunded to it once (rulings R8, R9).

Kept apart from ``service.py`` (the ledger primitives) to hold both under the file-size
limit, like ``adjust.py``. Both book through :func:`service.post`, flush and never commit.

- :func:`debit_purchase` — the order is paid from the balance: C ``user_wallet`` /
  D ``house_payments_received``, key ``purchase:order:{order_id}``.
- :func:`credit_order_refund` — the order's money comes back to the balance. A
  balance-paid order: D ``user_wallet`` / C ``house_payments_received`` (the purchase
  undone). A kassa-paid order books nothing when it is paid, so its refund is the shape of
  a top-up: D ``user_wallet`` / C ``provider_clearing:<kassa>`` — the kassa's money becomes
  balance. Key ``refund:order:{order_id}``.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.modules.wallet.models import WalletAccount, WalletTransaction
from csmarket.modules.wallet.service import (
    InsufficientBalanceError,
    Leg,
    Reference,
    _provider_clearing,
    _replay,
    _transaction_by_key,
    balance,
    ensure_account,
    post,
    user_account,
    user_usd_account,
)

#: ``orders.paid_with`` (and ``payments.provider``) of an order paid from the balance.
WALLET = "wallet"
#: Every ``orders.paid_with`` a refund can come from: the balance or one of our kassas.
#: ``orders.paid_with`` of an API order paid from the dollar balance.
USD_WALLET = "usd_wallet"
REFUND_SOURCES: frozenset[str] = frozenset({WALLET, "click", "payme", "uzum", "mock", USD_WALLET})


async def _house_payments_received(db: AsyncSession) -> WalletAccount:
    """The house account that takes the money customers pay from their balance."""
    return await ensure_account(
        db, owner_type="house", owner_id="house", kind="house_payments_received"
    )


async def debit_purchase(
    db: AsyncSession, *, user_id: str, order_id: str, amount: Decimal
) -> WalletTransaction:
    """Pay order ``order_id`` from the user's balance: C ``user_wallet`` / D
    ``house_payments_received``.

    The user's wallet is locked ``FOR UPDATE`` first (lock order: the caller already holds
    the order row), then the key ``purchase:order:{order_id}`` is looked up — a replay
    returns the booked transaction before any balance check — and a balance below
    ``amount`` is refused: our code never drives a balance below zero. Flushes, never
    commits.

    Raises:
        InsufficientBalanceError: ``code="balance_too_low"`` — the balance does not cover
            ``amount``; nothing is written.
        ConflictError: ``code="idempotency_mismatch"`` — the key booked another kind.
    """
    key = f"purchase:order:{order_id}"
    wallet = await user_account(db, user_id, lock=True)
    existing = await _transaction_by_key(db, key)
    if existing is not None:
        return _replay(existing, "purchase")
    if await balance(db, wallet.id) < amount:
        raise InsufficientBalanceError(
            "the balance does not cover this order", code="balance_too_low"
        )
    house = await _house_payments_received(db)
    return await post(
        db,
        kind="purchase",
        legs=[Leg(wallet.id, "C", amount), Leg(house.id, "D", amount)],
        idempotency_key=key,
        reference=Reference(type="order", id=order_id),
        actor="orders",
    )


async def credit_order_refund(
    db: AsyncSession,
    *,
    user_id: str,
    order_id: str,
    amount: Decimal,
    paid_with: str,
    actor: str = "orders",
) -> WalletTransaction:
    """Refund order ``order_id`` to the user's balance, once.

    ``paid_with == "wallet"``: D ``user_wallet`` / C ``house_payments_received``; any kassa:
    D ``user_wallet`` / C ``provider_clearing:<paid_with>``. A refund already booked (key
    ``refund:order:{order_id}``) is returned as is. A credit needs no lock on the wallet.
    Flushes, never commits.

    Args:
        db: Session; the caller holds the order row ``FOR UPDATE``.
        user_id: The buyer.
        order_id: The refunded order.
        amount: Whole soʻm the buyer paid (``orders.price_uzs``).
        paid_with: ``orders.paid_with`` — ``wallet`` or the kassa's slug.
        actor: Who books it (``orders`` for the automatic refunds, ``admin:<id>``).

    Raises:
        ValueError: ``paid_with`` is ``usd_wallet`` (use :func:`credit_order_refund_usd`) or
            none of :data:`REFUND_SOURCES` — a caller bug, refused
            before anything is written (it must not mint a stray clearing account).
        ConflictError: ``code="idempotency_mismatch"`` — the key booked another kind.
    """
    if paid_with == USD_WALLET:
        raise ValueError("a USD wallet order is refunded by credit_order_refund_usd")
    if paid_with not in REFUND_SOURCES:
        raise ValueError(f"paid_with {paid_with!r} is not a refund source")
    wallet = await user_account(db, user_id)
    source = (
        await _house_payments_received(db)
        if paid_with == WALLET
        else await _provider_clearing(db, paid_with)
    )
    return await post(
        db,
        kind="refund",
        legs=[Leg(wallet.id, "D", amount), Leg(source.id, "C", amount)],
        idempotency_key=f"refund:order:{order_id}",
        reference=Reference(type="order", id=order_id),
        actor=actor,
        metadata={"paid_with": paid_with},
    )


async def _house_payments_received_usd(db: AsyncSession) -> WalletAccount:
    """The house account that takes the dollars customers pay from their USD balance."""
    return await ensure_account(
        db, owner_type="house", owner_id="house", kind="house_payments_received_usd"
    )


async def debit_purchase_usd(
    db: AsyncSession, *, user_id: str, order_id: str, units: Decimal
) -> WalletTransaction:
    """Pay order ``order_id`` from the user's USD balance (milli-USD ``units``).

    As :func:`debit_purchase` on the dollar accounts: C ``user_wallet_usd`` /
    D ``house_payments_received_usd``, key ``purchase:order:usd:{order_id}``, the wallet locked
    first, a replay returned before the balance check. Flushes, never commits.

    Raises:
        InsufficientBalanceError: ``code="balance_too_low"`` — nothing is written.
        ConflictError: ``code="idempotency_mismatch"`` — the key booked another kind.
    """
    key = f"purchase:order:usd:{order_id}"
    wallet = await user_usd_account(db, user_id, lock=True)
    existing = await _transaction_by_key(db, key)
    if existing is not None:
        return _replay(existing, "purchase")
    if await balance(db, wallet.id) < units:
        raise InsufficientBalanceError(
            "the balance does not cover this order", code="balance_too_low"
        )
    house = await _house_payments_received_usd(db)
    return await post(
        db,
        kind="purchase",
        legs=[Leg(wallet.id, "C", units), Leg(house.id, "D", units)],
        idempotency_key=key,
        reference=Reference(type="order", id=order_id),
        actor="orders",
    )


async def credit_order_refund_usd(
    db: AsyncSession, *, user_id: str, order_id: str, units: Decimal, actor: str = "orders"
) -> WalletTransaction:
    """Refund order ``order_id`` to the user's USD balance, once.

    D ``user_wallet_usd`` / C ``house_payments_received_usd``, key ``refund:order:usd:{order_id}``;
    a refund already booked is returned as is. Flushes, never commits.

    Raises:
        ConflictError: ``code="idempotency_mismatch"`` — the key booked another kind.
    """
    wallet = await user_usd_account(db, user_id)
    house = await _house_payments_received_usd(db)
    return await post(
        db,
        kind="refund",
        legs=[Leg(wallet.id, "D", units), Leg(house.id, "C", units)],
        idempotency_key=f"refund:order:usd:{order_id}",
        reference=Reference(type="order", id=order_id),
        actor=actor,
        metadata={"paid_with": USD_WALLET},
    )


__all__ = [
    "REFUND_SOURCES",
    "USD_WALLET",
    "WALLET",
    "credit_order_refund",
    "credit_order_refund_usd",
    "debit_purchase",
    "debit_purchase_usd",
]
