"""A visit by a partner's link: counted at most once per visitor per UTC day.

The dedup follows the article views: a daily random salt in Redis
(``referrals:visit_salt:YYYY-MM-DD``) and a key ``referrals:visited:<sha256(salt|ip|partner)>``
until midnight — Tashkent days here, so a visit lands in the partner's Tashkent month. No IP is stored; Redis being down means the visit is not counted.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core import redis as core_redis
from csmarket.core.clock import now
from csmarket.modules.referrals.models import ReferralPartner, ReferralVisitDay
from csmarket.modules.users.api import User

TASHKENT = ZoneInfo("Asia/Tashkent")


def _next_midnight(at: datetime) -> datetime:
    return (at + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)


async def earning_partner(db: AsyncSession, code: str) -> ReferralPartner | None:
    """The active partner of ``code`` whose account is not banned; else ``None``."""
    return await db.scalar(
        select(ReferralPartner)
        .join(User, User.id == ReferralPartner.user_id)
        .where(
            ReferralPartner.code == code.strip().lower(),
            ReferralPartner.active.is_(True),
            User.banned_at.is_(None),
        )
    )


async def _first_today(partner_id: str, ip: str, at: datetime) -> bool:
    day = at.strftime("%Y-%m-%d")
    try:
        redis = core_redis.get_redis()
        salt_key = f"referrals:visit_salt:{day}"
        await redis.set(salt_key, secrets.token_hex(32), nx=True, ex=2 * 24 * 3600)
        salt = await redis.get(salt_key)
        if salt is None:
            return False
        salt_text = salt.decode() if isinstance(salt, bytes) else str(salt)
        digest = hashlib.sha256(f"{salt_text}|{ip}|{partner_id}".encode()).hexdigest()
        ttl = max(1, int((_next_midnight(at) - at).total_seconds()))
        return bool(await redis.set(f"referrals:visited:{digest}", "1", nx=True, ex=ttl))
    except (RedisError, ConnectionError, OSError):
        return False


async def count_visit(db: AsyncSession, partner: ReferralPartner, *, ip: str) -> bool:
    """Count one visit unless this visitor was counted today (a Tashkent day, as the partner's
    months are); commits. ``False`` when not counted."""
    at = now().astimezone(TASHKENT)
    if not await _first_today(partner.user_id, ip, at):
        return False
    stmt = insert(ReferralVisitDay).values(partner_id=partner.user_id, day=at.date(), visits=1)
    await db.execute(
        stmt.on_conflict_do_update(
            index_elements=["partner_id", "day"],
            set_={"visits": ReferralVisitDay.visits + 1},
        )
    )
    await db.commit()
    return True


__all__ = ["count_visit", "earning_partner"]
