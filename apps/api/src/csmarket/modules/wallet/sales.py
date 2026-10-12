"""A sale on the ledger: the user's money for skins they sold us (spec 2026-10-08 §4).

- :func:`credit_sale` — D ``user_wallet`` / C ``house_skin_buys``, key ``sale:{sale_id}``: at
  most once per sale, whatever the webhooks, polls and races.
- :func:`credit_payout_return` — a card payout an admin rejected comes to the balance
  instead: the same legs, key ``payout_return:{request_id}`` (``…:{n}`` after ``n`` undos).
- :func:`debit_payout_return` — the admin undid that «Отклонить» within minutes: the credit
  comes back off the balance (C ``user_wallet`` / D ``house_skin_buys``), key
  ``payout_return_reversal:{request_id}:{n}``, refused when the balance no longer covers it.

The spec writes the credit «debit house_skin_buys / credit user_wallet» from the house's
side; on this ledger a user's money is a debit balance (``NORMAL_SIDE["user_wallet"] == "D"``,
as a top-up books it), so the legs are mirrored and ``house_skin_buys`` is credit-normal. A
credit needs no lock on the wallet. Both flush, never commit.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.modules.wallet.models import WalletAccount, WalletTransaction
from csmarket.modules.wallet.service import (
    InsufficientBalanceError,
    Leg,
    Reference,
    _replay,
    _transaction_by_key,
    balance,
    ensure_account,
    post,
    user_account,
)


async def _house_skin_buys(db: AsyncSession) -> WalletAccount:
    """The house account that pays for skins users sell us."""
    return await ensure_account(db, owner_type="house", owner_id="house", kind="house_skin_buys")


async def _credit(
    db: AsyncSession,
    *,
    kind: str,
    key: str,
    user_id: str,
    sale_id: str,
    amount: Decimal,
    actor: str,
) -> WalletTransaction:
    wallet = await user_account(db, user_id)
    house = await _house_skin_buys(db)
    return await post(
        db,
        kind=kind,
        legs=[Leg(wallet.id, "D", amount), Leg(house.id, "C", amount)],
        idempotency_key=key,
        reference=Reference(type="sale", id=sale_id),
        actor=actor,
    )


async def credit_sale(
    db: AsyncSession, *, user_id: str, sale_id: str, amount: Decimal
) -> WalletTransaction:
    """Pay sale ``sale_id`` to the user's balance, once (a replay returns the first)."""
    return await _credit(
        db,
        kind="sale_credit",
        key=f"sale:{sale_id}",
        user_id=user_id,
        sale_id=sale_id,
        amount=amount,
        actor="sales",
    )


async def credit_payout_return(
    db: AsyncSession,
    *,
    user_id: str,
    sale_id: str,
    request_id: str,
    amount: Decimal,
    actor: str,
    attempt: int = 0,
) -> WalletTransaction:
    """Credit a rejected card payout to the balance, once per request and ``attempt`` (the
    request's undo count: a rejection undone and made again is a new credit)."""
    suffix = f":{attempt}" if attempt else ""
    return await _credit(
        db,
        kind="payout_return",
        key=f"payout_return:{request_id}{suffix}",
        user_id=user_id,
        sale_id=sale_id,
        amount=amount,
        actor=actor,
    )


async def debit_payout_return(
    db: AsyncSession,
    *,
    user_id: str,
    sale_id: str,
    request_id: str,
    amount: Decimal,
    actor: str,
    attempt: int,
) -> WalletTransaction:
    """Take back the credit of an undone rejection (``attempt`` = the request's undo count
    before this undo). The wallet is locked ``FOR UPDATE`` first, a replay returns the booked
    transaction, and a balance below ``amount`` is refused: the seller may have spent it.
    Flushes, never commits.

    Raises:
        InsufficientBalanceError: ``code="balance_spent"`` — nothing is written.
        ConflictError: the wallet is frozen (``post``).
    """
    key = f"payout_return_reversal:{request_id}:{attempt}"
    wallet = await user_account(db, user_id, lock=True)
    existing = await _transaction_by_key(db, key)
    if existing is not None:
        return _replay(existing, "payout_return_reversal")
    if await balance(db, wallet.id) < amount:
        raise InsufficientBalanceError(
            "the seller already spent the returned money", code="balance_spent"
        )
    house = await _house_skin_buys(db)
    return await post(
        db,
        kind="payout_return_reversal",
        legs=[Leg(wallet.id, "C", amount), Leg(house.id, "D", amount)],
        idempotency_key=key,
        reference=Reference(type="sale", id=sale_id),
        actor=actor,
    )


__all__ = ["credit_payout_return", "credit_sale", "debit_payout_return"]
