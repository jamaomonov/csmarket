"""Admin balance corrections: ``admin_adjust`` (spec §13, ruling R13).

Kept apart from ``service.py`` (the ledger primitives) to hold both under the file-size
limit. Like every wallet writer it books through :func:`service.post`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.errors import ConflictError, ValidationError
from csmarket.modules.wallet.models import WalletAccount, WalletPosting, WalletTransaction
from csmarket.modules.wallet.service import (
    InsufficientBalanceError,
    Leg,
    _transaction_by_key,
    balance,
    ensure_account,
    post,
    user_account,
    user_usd_account,
)

#: Largest admin adjustment either way, in soʻm.
ADMIN_ADJUST_MAX = Decimal(100_000_000)
#: Largest admin adjustment either way, in milli-USD ($100 000).
ADMIN_ADJUST_USD_MAX = Decimal(100_000_000)


def _validate_adjust(amount: Decimal, reason: str, maximum: Decimal) -> None:
    """A non-zero whole soʻm within ``ADMIN_ADJUST_MAX`` and a reason that is not blank."""
    if (
        not amount.is_finite()
        or amount == 0
        or amount != amount.to_integral_value()
        or abs(amount) > maximum
    ):
        raise ValidationError(
            "amount must be a non-zero whole soʻm within the limit",
            code="adjust_amount",
            max=int(maximum),
        )
    if not reason.strip():
        raise ValidationError("a reason is required", code="adjust_reason")


async def _signed_user_leg(db: AsyncSession, txn: WalletTransaction, account_id: str) -> Decimal:
    """``txn``'s signed amount on ``account_id`` (a ``user_wallet``: D is +); 0 if absent."""
    signed = case(
        (WalletPosting.direction == "D", WalletPosting.amount), else_=-WalletPosting.amount
    )
    total = await db.scalar(
        select(func.coalesce(func.sum(signed), 0)).where(
            WalletPosting.transaction_id == txn.id, WalletPosting.account_id == account_id
        )
    )
    return Decimal(total or 0)


async def _same_adjustment(
    db: AsyncSession, txn: WalletTransaction, wallet_id: str, amount: Decimal, tx_kind: str
) -> WalletTransaction:
    """``txn`` when it is this adjustment (kind, this wallet, this signed amount); else 409."""
    if txn.kind != tx_kind or await _signed_user_leg(db, txn, wallet_id) != amount:
        raise ConflictError(
            "this Idempotency-Key was used for another adjustment", code="idempotency_mismatch"
        )
    return txn


async def _adjust(
    db: AsyncSession,
    *,
    user_id: str,
    amount: Decimal,
    reason: str,
    admin_id: str,
    idempotency_key: str,
    wallet_for: Callable[..., Awaitable[WalletAccount]],
    house_kind: str,
    tx_kind: str,
    key_prefix: str,
    maximum: Decimal,
) -> WalletTransaction:
    """The shared body of :func:`admin_adjust` and :func:`admin_adjust_usd`."""
    _validate_adjust(amount, reason, maximum)
    key = f"{key_prefix}{idempotency_key}"
    wallet = await wallet_for(db, user_id, lock=True)
    existing = await _transaction_by_key(db, key)
    if existing is not None:
        return await _same_adjustment(db, existing, wallet.id, amount, tx_kind)
    house = await ensure_account(db, owner_type="house", owner_id="house", kind=house_kind)
    size = abs(amount)
    if amount < 0 and await balance(db, wallet.id) < size:
        raise InsufficientBalanceError(
            "the balance does not cover this clawback", code="balance_too_low"
        )
    legs = (
        [Leg(wallet.id, "D", size), Leg(house.id, "C", size)]
        if amount > 0
        else [Leg(house.id, "D", size), Leg(wallet.id, "C", size)]
    )
    txn = await post(
        db,
        kind=tx_kind,
        legs=legs,
        idempotency_key=key,
        actor=f"admin:{admin_id}",
        metadata={"reason": reason.strip()},
    )
    # ``post`` returns a concurrent winner of the same key — possibly another user's.
    return await _same_adjustment(db, txn, wallet.id, amount, tx_kind)


async def admin_adjust(
    db: AsyncSession,
    *,
    user_id: str,
    amount: Decimal,
    reason: str,
    admin_id: str,
    idempotency_key: str,
) -> WalletTransaction:
    """An admin's balance correction: credit (``amount > 0``) or clawback (``amount < 0``).

    Credit: D ``user_wallet`` / C ``house_adjustments``; clawback: the mirror. The user's
    wallet is locked ``FOR UPDATE`` first, then the key ``admin_adjust:<idempotency_key>``
    is looked up — a replay returns the booked transaction before any balance check — and
    a clawback the balance does not cover is refused (ruling R13: never below zero).
    ``actor`` is ``admin:<admin_id>``, ``metadata`` ``{"reason"}``. Flushes, never commits.

    Raises:
        ValidationError: ``code="adjust_amount"`` (zero, fractional, non-finite or beyond
            ``ADMIN_ADJUST_MAX``) or ``code="adjust_reason"`` (blank).
        ConflictError: ``code="idempotency_mismatch"`` — the key already booked (or a
            concurrent request just booked) another user's or another amount's adjustment.
        InsufficientBalanceError: ``code="balance_too_low"`` — the clawback exceeds the
            balance.
    """
    return await _adjust(
        db,
        user_id=user_id,
        amount=amount,
        reason=reason,
        admin_id=admin_id,
        idempotency_key=idempotency_key,
        wallet_for=user_account,
        house_kind="house_adjustments",
        tx_kind="admin_adjust",
        key_prefix="admin_adjust:",
        maximum=ADMIN_ADJUST_MAX,
    )


async def admin_adjust_usd(
    db: AsyncSession,
    *,
    user_id: str,
    amount: Decimal,
    reason: str,
    admin_id: str,
    idempotency_key: str,
) -> WalletTransaction:
    """:func:`admin_adjust` in dollars: milli-USD units, ``user_wallet_usd`` against
    ``house_adjustments_usd``, limit ``ADMIN_ADJUST_USD_MAX``, key ``admin_adjust_usd:<key>``."""
    return await _adjust(
        db,
        user_id=user_id,
        amount=amount,
        reason=reason,
        admin_id=admin_id,
        idempotency_key=idempotency_key,
        wallet_for=user_usd_account,
        house_kind="house_adjustments_usd",
        tx_kind="admin_adjust_usd",
        key_prefix="admin_adjust_usd:",
        maximum=ADMIN_ADJUST_USD_MAX,
    )


__all__ = ["ADMIN_ADJUST_MAX", "ADMIN_ADJUST_USD_MAX", "admin_adjust", "admin_adjust_usd"]
