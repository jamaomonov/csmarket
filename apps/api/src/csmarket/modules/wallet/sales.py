"""A sale on the ledger: the user's money for skins they sold us (spec 2026-10-08 §4).

- :func:`credit_sale` — D ``user_wallet`` / C ``house_skin_buys``, key ``sale:{sale_id}``: at
  most once per sale, whatever the webhooks, polls and races.
- :func:`credit_payout_return` — a card payout an admin rejected comes to the balance
  instead: the same legs, key ``payout_return:{request_id}``.

The spec writes the credit «debit house_skin_buys / credit user_wallet» from the house's
side; on this ledger a user's money is a debit balance (``NORMAL_SIDE["user_wallet"] == "D"``,
as a top-up books it), so the legs are mirrored and ``house_skin_buys`` is credit-normal. A
credit needs no lock on the wallet. Both flush, never commit.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.modules.wallet.models import WalletAccount, WalletTransaction
from csmarket.modules.wallet.service import Leg, Reference, ensure_account, post, user_account


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
) -> WalletTransaction:
    """Credit a rejected card payout to the balance, once per request."""
    return await _credit(
        db,
        kind="payout_return",
        key=f"payout_return:{request_id}",
        user_id=user_id,
        sale_id=sale_id,
        amount=amount,
        actor=actor,
    )


__all__ = ["credit_payout_return", "credit_sale"]
