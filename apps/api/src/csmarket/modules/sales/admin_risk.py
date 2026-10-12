"""What the admin needs to judge a card payout before sending money (admin review 2026-10-12
H2, H3): flags on the queue's rows and the request page's «Риски» block.

Flags, one batched query per kind for a page of rows:

- ``banned`` — the account is banned; ``wallet_frozen`` — its soʻm wallet is frozen. Either
  blocks «Выплачено» unless the admin overrides it with a reason (:mod:`.admin_payouts`).
- ``sell_blocked`` — an admin stopped the user from selling.
- ``new_account`` — signed up less than :data:`NEW_ACCOUNT` ago.
- ``shared_card`` — the same card (by ``number_fp``) is saved on another account.

Reads only; the Steam profile link is built from the Steam ID the admin already sees on the
user's page, no Steam call is made.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.money import wire_uzs
from csmarket.modules.sales.admin_schemas import AdminUserOut, PayoutFlag, PayoutRiskOut
from csmarket.modules.sales.models import PayoutCard, PayoutRequest, Sale, SaleBlock
from csmarket.modules.sales.schemas import plain
from csmarket.modules.users.api import User
from csmarket.modules.wallet.api import WalletAccount

#: An account younger than this is flagged ``new_account``.
NEW_ACCOUNT = timedelta(days=7)
#: How many other accounts with the same card the page names.
SHARED_LIMIT = 10
#: Sales that paid or will pay the seller (not closed, not reverted).
_SOLD = ("hold", "credited", "payout")


async def frozen_users(db: AsyncSession, user_ids: Iterable[str]) -> set[str]:
    """Which of ``user_ids`` have a frozen soʻm wallet (one query, nothing created)."""
    wanted = set(user_ids)
    if not wanted:
        return set()
    rows = await db.scalars(
        select(WalletAccount.owner_id).where(
            WalletAccount.owner_type == "user",
            WalletAccount.kind == "user_wallet",
            WalletAccount.status == "frozen",
            WalletAccount.owner_id.in_(wanted),
        )
    )
    return set(rows.all())


async def shared_fps(db: AsyncSession, fps: Iterable[str | None]) -> set[str]:
    """Which fingerprints are saved on more than one account."""
    wanted = {fp for fp in fps if fp}
    if not wanted:
        return set()
    rows = await db.scalars(
        select(PayoutCard.number_fp)
        .where(PayoutCard.number_fp.in_(wanted))
        .group_by(PayoutCard.number_fp)
        .having(func.count(func.distinct(PayoutCard.user_id)) > 1)
    )
    return {fp for fp in rows.all() if fp}


async def row_flags(
    db: AsyncSession, requests: list[PayoutRequest], cards: dict[str, PayoutCard]
) -> dict[str, list[PayoutFlag]]:
    """``request id → flags`` for a page of the queue (five queries whatever its size)."""
    uids = {r.user_id for r in requests}
    if not uids:
        return {}
    users = {
        u.id: u
        for u in (
            await db.execute(
                select(User.id, User.banned_at, User.created_at).where(User.id.in_(uids))
            )
        ).all()
    }
    frozen = await frozen_users(db, uids)
    blocked = set(
        (await db.scalars(select(SaleBlock.user_id).where(SaleBlock.user_id.in_(uids)))).all()
    )
    shared = await shared_fps(db, (c.number_fp for c in cards.values()))
    reverted = set(
        (
            await db.scalars(
                select(Sale.id).where(
                    Sale.id.in_({r.sale_id for r in requests}),
                    Sale.attention_reason == "rolled_back",
                )
            )
        ).all()
    )
    young = now() - NEW_ACCOUNT
    out: dict[str, list[PayoutFlag]] = {}
    for r in requests:
        user = users.get(r.user_id)
        fp = cards[r.card_id].number_fp if r.card_id in cards else None
        flags: list[PayoutFlag] = []
        if user is not None and user.banned_at is not None:
            flags.append("banned")
        if r.user_id in frozen:
            flags.append("wallet_frozen")
        if r.user_id in blocked:
            flags.append("sell_blocked")
        if user is not None and user.created_at > young:
            flags.append("new_account")
        if fp in shared:
            flags.append("shared_card")
        if r.sale_id in reverted:
            flags.append("rolled_back")
        out[r.id] = flags
    return out


async def _sums(db: AsyncSession, user_id: str, fp: str | None) -> dict[str, Decimal | int]:
    """Totals of the seller (and of the card, by fingerprint)."""
    sold_count, sold_uzs = (
        await db.execute(
            select(func.count(), func.coalesce(func.sum(Sale.payout_uzs), 0)).where(
                Sale.user_id == user_id, Sale.status.in_(_SOLD)
            )
        )
    ).one()
    paid_count, paid_uzs = (
        await db.execute(
            select(func.count(), func.coalesce(func.sum(PayoutRequest.amount_uzs), 0)).where(
                PayoutRequest.user_id == user_id, PayoutRequest.status == "paid"
            )
        )
    ).one()
    day_count, day_usd = (
        await db.execute(
            select(func.count(), func.coalesce(func.sum(Sale.quoted_usd), 0)).where(
                Sale.user_id == user_id,
                Sale.created_at > now() - timedelta(hours=24),
                Sale.status.not_in(("closed", "reverted")),
            )
        )
    ).one()
    card_paid = Decimal(0)
    if fp is not None:
        card_paid = Decimal(
            await db.scalar(
                select(func.coalesce(func.sum(PayoutRequest.amount_uzs), 0))
                .join(PayoutCard, PayoutCard.id == PayoutRequest.card_id)
                .where(PayoutCard.number_fp == fp, PayoutRequest.status == "paid")
            )
            or 0
        )
    return {
        "sold_count": int(sold_count),
        "sold_uzs": Decimal(sold_uzs),
        "paid_count": int(paid_count),
        "paid_uzs": Decimal(paid_uzs),
        "day_count": int(day_count),
        "day_usd": Decimal(day_usd),
        "card_paid_uzs": card_paid,
    }


async def _shared_users(db: AsyncSession, user_id: str, fp: str | None) -> list[AdminUserOut]:
    """Other accounts that saved the same card (live or deleted), newest card first."""
    if fp is None:
        return []
    rows = await db.execute(
        select(User.id, User.display_name)
        .join(PayoutCard, PayoutCard.user_id == User.id)
        .where(PayoutCard.number_fp == fp, User.id != user_id)
        .group_by(User.id, User.display_name)
        .order_by(func.max(PayoutCard.created_at).desc())
        .limit(SHARED_LIMIT)
    )
    return [AdminUserOut(id=uid, display_name=name) for uid, name in rows.all()]


async def payout_risk(db: AsyncSession, request: PayoutRequest, card: PayoutCard) -> PayoutRiskOut:
    """The request page's «Риски» block."""
    user = await db.get(User, request.user_id)
    block = await db.get(SaleBlock, request.user_id, populate_existing=True)
    frozen = request.user_id in await frozen_users(db, [request.user_id])
    sums = await _sums(db, request.user_id, card.number_fp)
    steam_id = user.steam_id if user is not None else None
    return PayoutRiskOut(
        steam_url=f"https://steamcommunity.com/profiles/{steam_id}" if steam_id else None,
        account_created_at=user.created_at if user is not None else None,
        banned=user is not None and user.banned_at is not None,
        ban_reason=user.ban_reason if user is not None else None,
        wallet_frozen=frozen,
        sell_blocked=block is not None,
        sell_block_reason=block.reason if block is not None else None,
        sold_count=int(sums["sold_count"]),
        sold_uzs=wire_uzs(Decimal(sums["sold_uzs"])),
        paid_count=int(sums["paid_count"]),
        paid_uzs=wire_uzs(Decimal(sums["paid_uzs"])),
        card_paid_uzs=wire_uzs(Decimal(sums["card_paid_uzs"])),
        day_count=int(sums["day_count"]),
        day_usd=plain(Decimal(sums["day_usd"])),
        card_known=card.number_fp is not None,
        shared_card_users=await _shared_users(db, request.user_id, card.number_fp),
    )


__all__ = [
    "NEW_ACCOUNT",
    "SHARED_LIMIT",
    "frozen_users",
    "payout_risk",
    "row_flags",
    "shared_fps",
]
