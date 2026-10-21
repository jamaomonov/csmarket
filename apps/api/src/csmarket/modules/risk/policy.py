"""A user's risk policy: the admin's read and save, and the kassa block at payment start."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.money import wire_uzs
from csmarket.modules.admin.api import record
from csmarket.modules.risk.models import PaymentHold, UserRiskPolicy
from csmarket.modules.risk.rule import money_in
from csmarket.modules.risk.schemas import AuthorOut, RiskPolicyIn, RiskPolicyOut
from csmarket.modules.users.api import User


async def policy_view(db: AsyncSession, user_id: str) -> RiskPolicyOut:
    """The policy (defaults when none) and the user's recent kassa money."""
    row = await db.get(UserRiskPolicy, user_id, populate_existing=True)
    author = None
    if row is not None and row.updated_by is not None:
        admin = await db.get(User, row.updated_by)
        if admin is not None:
            author = AuthorOut(id=admin.id, display_name=admin.display_name)
    holds = await db.scalar(
        select(func.count())
        .select_from(PaymentHold)
        .where(PaymentHold.user_id == user_id, PaymentHold.decision.is_(None))
    )
    return RiskPolicyOut(
        trusted=row.trusted if row else False,
        kassa_blocked=row.kassa_blocked if row else False,
        max_amount_uzs=wire_uzs(row.max_amount_uzs) if row and row.max_amount_uzs else None,
        window_hours=row.window_hours if row else 24,
        note=row.note if row else None,
        updated_at=row.updated_at if row else None,
        updated_by=author,
        money_in_24h_uzs=wire_uzs(await money_in(db, user_id=user_id, hours=24)),
        money_in_7d_uzs=wire_uzs(await money_in(db, user_id=user_id, hours=24 * 7)),
        open_holds=int(holds or 0),
    )


async def save_policy(db: AsyncSession, *, user_id: str, body: RiskPolicyIn, admin_id: str) -> None:
    """Upsert the user's policy and audit it (the note is the admin's reason). Flushes only."""
    row = await db.get(UserRiskPolicy, user_id, with_for_update=True, populate_existing=True)
    if row is None:
        row = UserRiskPolicy(user_id=user_id)
        db.add(row)
    row.trusted = body.trusted
    row.kassa_blocked = body.kassa_blocked
    row.max_amount_uzs = Decimal(body.max_amount_uzs) if body.max_amount_uzs else None
    row.window_hours = body.window_hours
    row.note = body.note
    row.updated_by = admin_id
    row.updated_at = now()
    await db.flush()
    await record(
        db,
        actor_id=admin_id,
        action="users.risk.update",
        target_type="user",
        target_id=user_id,
        payload={
            "trusted": body.trusted,
            "kassa_blocked": body.kassa_blocked,
            "max_amount_uzs": str(body.max_amount_uzs) if body.max_amount_uzs else None,
            "window_hours": body.window_hours,
            "note": body.note,
        },
    )
