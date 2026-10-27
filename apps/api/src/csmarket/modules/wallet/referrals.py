"""A partner's reward on the ledger (spec 2026-10-27-referrals, ADR-0026).

:func:`credit_referral_reward` — D ``user_wallet`` / C ``house_referrals``, key
``referral_reward:{order_id}``. ``house_referrals`` is credit-normal: it grows with what
partners were paid, as ``house_skin_buys`` does for sales. The reference is
``("referral", order_id)``: the partner's history shows no order number (the buyer is never
theirs to see). Flushes, never commits; a frozen wallet raises the ledger's ``ConflictError``.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.modules.wallet.models import WalletTransaction
from csmarket.modules.wallet.service import Leg, Reference, ensure_account, post, user_account


async def credit_referral_reward(
    db: AsyncSession, *, user_id: str, order_id: str, amount: Decimal
) -> WalletTransaction:
    """Pay the partner ``user_id`` its reward for order ``order_id``, once (a replay returns
    the first)."""
    wallet = await user_account(db, user_id)
    house = await ensure_account(db, owner_type="house", owner_id="house", kind="house_referrals")
    return await post(
        db,
        kind="referral_reward",
        legs=[Leg(wallet.id, "D", amount), Leg(house.id, "C", amount)],
        idempotency_key=f"referral_reward:{order_id}",
        reference=Reference(type="referral", id=order_id),
        actor="referrals",
    )


__all__ = ["credit_referral_reward"]
