"""Tie a new account to the partner whose link it came by (spec 2026-10-27-referrals).

Only an account created by this very sign-in through the storefront is tied; an existing
account never is, whatever link it opens later. Flushes, never commits.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.logging import get_logger
from csmarket.modules.referrals.models import ReferralAttribution
from csmarket.modules.referrals.visits import earning_partner
from csmarket.modules.users.api import User

log = get_logger("csmarket.referrals.attribution")


async def attribute_new(db: AsyncSession, *, user: User, code: str | None) -> bool:
    """Write the attribution of new account ``user`` to the partner of ``code``.

    Nothing happens without a code, for an unknown, inactive or banned partner, or for the
    partner's own account.

    Returns:
        Whether the account was tied.
    """
    if not code:
        return False
    partner = await earning_partner(db, code)
    if partner is None or partner.user_id == user.id:
        return False
    db.add(ReferralAttribution(user_id=user.id, partner_id=partner.user_id, attributed_at=now()))
    await db.flush()
    log.info("referrals.attributed", partner=partner.code)
    return True


__all__ = ["attribute_new"]
