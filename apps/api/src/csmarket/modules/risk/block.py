"""The kassa block at payment start. Kept apart from ``policy`` (which imports ``admin``) so
``payments`` and ``orders`` can import it through ``risk.api`` without an import cycle."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.errors import KassaBlockedError
from csmarket.modules.risk.models import UserRiskPolicy


async def ensure_kassa_allowed(db: AsyncSession, user_id: str) -> None:
    """Refuse to start a kassa payment for a user the admin blocked.

    Raises:
        KassaBlockedError: the user's policy has ``kassa_blocked``.
    """
    blocked = await db.scalar(
        select(UserRiskPolicy.kassa_blocked).where(UserRiskPolicy.user_id == user_id)
    )
    if blocked:
        raise KassaBlockedError(
            "kassa payments are blocked for this account", code="kassa_payment_blocked"
        )
