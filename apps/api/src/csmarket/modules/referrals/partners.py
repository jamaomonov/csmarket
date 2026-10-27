"""The admin's «Партнёры»: make an account a partner, change its terms, list and page them.

Every write is audited in the caller's transaction (``referrals.partner.create`` / ``update``):
the payload carries the code, percent, term and switch — never the admin's note. Flushes,
never commits.
"""

from __future__ import annotations

import re
from decimal import Decimal

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.errors import ConflictError, NotFoundError, ValidationError
from csmarket.modules.admin.api import AuditPayload, record
from csmarket.modules.orders.api import Order
from csmarket.modules.referrals import cursor
from csmarket.modules.referrals.models import (
    CODE_PATTERN,
    ReferralAttribution,
    ReferralPartner,
    ReferralReward,
)
from csmarket.modules.referrals.schemas import (
    AdminPartnerDetailOut,
    AdminPartnerOut,
    AdminRewardOut,
    PartnerIn,
    PartnerPatch,
    PartnerRefOut,
    PartnerTotals,
    UserReferralOut,
)
from csmarket.modules.referrals.stats import by_month, partner_totals, som
from csmarket.modules.users.api import User, get_user_by_id, set_roles

PARTNER_ROLE = "partner"
PAGE = 50
_CODE = re.compile(CODE_PATTERN)


def clean_code(raw: str) -> str:
    """The code as stored: trimmed, lower-case, ``^[a-z0-9-]{3,32}$``.

    Raises:
        ValidationError: ``code="code_invalid"``.
    """
    code = raw.strip().lower()
    if not _CODE.fullmatch(code):
        raise ValidationError(
            "the code must be 3–32 latin letters, digits or -", code="code_invalid"
        )
    return code


async def _code_free(db: AsyncSession, code: str, *, mine: str | None = None) -> None:
    owner = await db.scalar(select(ReferralPartner.user_id).where(ReferralPartner.code == code))
    if owner is not None and owner != mine:
        raise ConflictError("this code is taken", code="code_taken")


def _out(partner: ReferralPartner, user: User, totals: PartnerTotals | None) -> AdminPartnerOut:
    return AdminPartnerOut(
        user_id=partner.user_id,
        display_name=user.display_name,
        steam_id=user.steam_id,
        code=partner.code,
        percent=partner.percent,
        term_months=partner.term_months,
        active=partner.active,
        note=partner.note,
        created_at=partner.created_at,
        totals=totals or PartnerTotals(),
    )


async def find(db: AsyncSession, user_id: str) -> ReferralPartner:
    """The partner of account ``user_id``.

    Raises:
        NotFoundError: ``code="partner_not_found"``.
    """
    partner = await db.get(ReferralPartner, user_id)
    if partner is None:
        raise NotFoundError("no such partner", code="partner_not_found")
    return partner


async def partner_out(db: AsyncSession, partner: ReferralPartner) -> AdminPartnerOut:
    """One partner with its totals."""
    user = await get_user_by_id(db, partner.user_id)
    assert user is not None  # the FK cascades: a partner always has its account
    totals = await partner_totals(db, [partner.user_id])
    return _out(partner, user, totals.get(partner.user_id))


async def create_partner(db: AsyncSession, *, body: PartnerIn, admin_id: str) -> AdminPartnerOut:
    """Make ``body.user_id`` a partner and give the account the ``partner`` role.

    Raises:
        NotFoundError: ``user_not_found``.
        ConflictError: ``partner_exists``, ``code_taken``.
        ValidationError: ``code_invalid``.
    """
    code = clean_code(body.code)
    user = await get_user_by_id(db, body.user_id)
    if user is None:
        raise NotFoundError("no such account", code="user_not_found")
    if await db.get(ReferralPartner, user.id) is not None:
        raise ConflictError("the account is a partner already", code="partner_exists")
    await _code_free(db, code)
    partner = ReferralPartner(
        user_id=user.id,
        code=code,
        percent=body.percent,
        term_months=body.term_months,
        note=body.note,
    )
    db.add(partner)
    await db.flush()
    await db.refresh(partner)
    await set_roles(db, user, [*user.roles, PARTNER_ROLE])
    payload: AuditPayload = {
        "code": code,
        "percent": str(body.percent),
        "term_months": body.term_months,
    }
    await record(
        db,
        actor_id=admin_id,
        action="referrals.partner.create",
        target_type="user",
        target_id=user.id,
        payload=payload,
    )
    return _out(partner, user, None)


async def _apply(db: AsyncSession, partner: ReferralPartner, patch: PartnerPatch) -> AuditPayload:
    changed: AuditPayload = {}
    fields = patch.model_fields_set
    if "code" in fields and patch.code is not None:
        code = clean_code(patch.code)
        if code != partner.code:
            brought = await db.scalar(
                select(exists().where(ReferralAttribution.partner_id == partner.user_id))
            )
            if brought:
                raise ConflictError("people came by this code", code="code_locked")
            await _code_free(db, code, mine=partner.user_id)
            partner.code = changed["code"] = code
    if "percent" in fields and patch.percent is not None:
        partner.percent = patch.percent
        changed["percent"] = str(patch.percent)
    if "term_months" in fields:
        partner.term_months = changed["term_months"] = patch.term_months
    if "active" in fields and patch.active is not None:
        partner.active = changed["active"] = patch.active
    if "note" in fields:
        partner.note = patch.note
        changed["note"] = True  # changed, never the text
    return changed


async def update_partner(
    db: AsyncSession, *, user_id: str, patch: PartnerPatch, admin_id: str
) -> AdminPartnerOut:
    """Change any of the partner's terms; audited with what changed.

    Raises:
        NotFoundError: ``partner_not_found``.
        ConflictError: ``code_locked``, ``code_taken``.
        ValidationError: ``code_invalid``.
    """
    partner = await find(db, user_id)
    changed = await _apply(db, partner, patch)
    if changed:
        partner.updated_at = now()
        await db.flush()
        await record(
            db,
            actor_id=admin_id,
            action="referrals.partner.update",
            target_type="user",
            target_id=partner.user_id,
            payload=changed,
        )
    return await partner_out(db, partner)


async def list_partners(db: AsyncSession) -> list[AdminPartnerOut]:
    """Every partner with its totals, most revenue brought first."""
    rows = (
        await db.execute(
            select(ReferralPartner, User)
            .join(User, User.id == ReferralPartner.user_id)
            .order_by(ReferralPartner.created_at.desc())
        )
    ).all()
    totals = await partner_totals(db, None)
    items = [_out(p, u, totals.get(p.user_id)) for p, u in rows]
    return sorted(items, key=lambda i: Decimal(i.totals.revenue_uzs), reverse=True)


async def detail(db: AsyncSession, *, user_id: str, after: str | None) -> AdminPartnerDetailOut:
    """A partner's page: terms, months and :data:`PAGE` rewards newest first."""
    partner = await find(db, user_id)
    r = ReferralReward
    q = (
        select(r, Order.number)
        .join(Order, Order.id == r.order_id)
        .where(r.partner_id == partner.user_id)
        .order_by(r.delivered_at.desc(), r.order_id.desc())
        .limit(PAGE + 1)
    )
    if (past := cursor.after(after)) is not None:
        q = q.where(past)
    rows = (await db.execute(q)).all()
    page = rows[:PAGE]
    last = page[-1][0] if len(rows) > PAGE else None
    return AdminPartnerDetailOut(
        partner=await partner_out(db, partner),
        months=await by_month(db, partner.user_id),
        rewards=[
            AdminRewardOut(
                order_number=number,
                delivered_at=w.delivered_at,
                base_uzs=som(w.base_uzs),
                percent=w.percent,
                amount_uzs=som(w.amount_uzs),
                status=w.status,  # type: ignore[arg-type]  # DB check constraint guarantees the set
                available_at=w.available_at,
                credited_at=w.credited_at,
                cancelled_reason=w.cancelled_reason,
            )
            for w, number in page
        ],
        next_cursor=cursor.encode(last.delivered_at, last.order_id) if last else None,
    )


async def user_referral(db: AsyncSession, user_id: str) -> UserReferralOut:
    """Who brought account ``user_id``, and whether it is a partner itself."""
    row = (
        await db.execute(
            select(ReferralAttribution, ReferralPartner, User)
            .join(ReferralPartner, ReferralPartner.user_id == ReferralAttribution.partner_id)
            .join(User, User.id == ReferralPartner.user_id)
            .where(ReferralAttribution.user_id == user_id)
        )
    ).first()
    is_partner = await db.get(ReferralPartner, user_id) is not None
    if row is None:
        return UserReferralOut(partner=None, attributed_at=None, is_partner=is_partner)
    attribution, partner, user = row
    return UserReferralOut(
        partner=PartnerRefOut(
            user_id=partner.user_id, code=partner.code, display_name=user.display_name
        ),
        attributed_at=attribution.attributed_at,
        is_partner=is_partner,
    )


__all__ = [
    "PAGE",
    "PARTNER_ROLE",
    "clean_code",
    "create_partner",
    "detail",
    "find",
    "list_partners",
    "partner_out",
    "update_partner",
    "user_referral",
]
