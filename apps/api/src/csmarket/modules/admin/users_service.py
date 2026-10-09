"""Admin users: find, show, ban/unban, adjust the balance (spec §13, rulings R13).

Every write is audited in ``admin_audit_log`` in the same transaction as the change; the
route then stores the replay and commits (the ``skins.admin_routes`` order). Writes lock the
target's ``users`` row first, so two requests on one account — a replayed key included —
run one after the other: the second sees the first's replay row, never a half-done state.
Lock order: ``users`` row (``FOR NO KEY UPDATE``), then (adjust) the user's wallet account.

Audit payloads carry the operator's reason and the amount, never a Steam ID, email or IP.
"""

from __future__ import annotations

import re
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.cursor import decode_cursor, encode_cursor
from csmarket.core.errors import ConflictError, NotFoundError
from csmarket.core.idempotency import load_replay, save_replay
from csmarket.core.money import wire_usd, wire_uzs
from csmarket.modules.admin.audit import record
from csmarket.modules.admin.deps import has_role
from csmarket.modules.admin.orders_service import recent_orders
from csmarket.modules.admin.users_schemas import (
    AdminEntryOut,
    AdminTopupOut,
    AdminUserCard,
    AdminUserDetail,
    AdminUserKeyBrief,
    AdminUserRow,
)
from csmarket.modules.auth.api import revoke_all_sessions
from csmarket.modules.payments.api import Payment, WalletTopup
from csmarket.modules.public_api.api import ApiKey
from csmarket.modules.users.api import User
from csmarket.modules.wallet.api import (
    admin_adjust,
    admin_adjust_usd,
    entries_for_admin,
    user_balance,
    user_balance_column,
    user_usd_balance,
)

#: Latest entries and top-ups on a card.
CARD_ROWS = 20
_STEAM_ID = re.compile(r"^\d{17}$", re.ASCII)


# --- reading ----------------------------------------------------------------------------


async def get_user(db: AsyncSession, user_id: str, *, lock: bool = False) -> User:
    """The user by id; ``lock`` re-reads the row ``FOR UPDATE``.

    Raises:
        NotFoundError: no such user, or ``user_id`` is not a UUID.
    """
    try:
        uuid.UUID(user_id)
    except ValueError as exc:
        raise NotFoundError("user not found") from exc
    stmt = select(User).where(User.id == user_id)
    if lock:
        # FOR NO KEY UPDATE: a refresh rotating mid-ban inserts a ``refresh_tokens`` row whose
        # FK takes KEY SHARE on this user; FOR UPDATE would block it (and can deadlock).
        stmt = stmt.with_for_update(key_share=True).execution_options(populate_existing=True)
    user = (await db.execute(stmt)).scalar_one_or_none()
    if user is None:
        raise NotFoundError("user not found")
    return user


def _like_escape(needle: str) -> str:
    return needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def list_users(
    db: AsyncSession,
    *,
    q: str | None,
    cursor: str | None,
    limit: int,
    has_api_key: bool | None = None,
) -> tuple[list[AdminUserRow], str | None]:
    """Users newest first, keyset on ``(created_at DESC, id DESC)``, with their balances.

    ``q`` matches the display name (case-insensitive substring, ``%``/``_`` literal) or
    an exact 17-digit Steam ID; ``has_api_key`` keeps users with (or without) a live key.
    One statement whatever the page size: the balance is a correlated subquery
    (``wallet.user_balance_column``), the live key an outer join (one live key per user).
    """
    balance = user_balance_column(User.id).label("balance")
    live = and_(ApiKey.user_id == User.id, ApiKey.revoked_at.is_(None))
    stmt = (
        select(User, balance, ApiKey.id, ApiKey.pricing_profile)
        .outerjoin(ApiKey, live)
        .order_by(User.created_at.desc(), User.id.desc())
        .limit(limit + 1)
    )
    if has_api_key is not None:
        stmt = stmt.where(ApiKey.id.is_not(None) if has_api_key else ApiKey.id.is_(None))
    needle = (q or "").strip()
    if needle:
        by_name = User.display_name.ilike(f"%{_like_escape(needle)}%", escape="\\")
        stmt = stmt.where(
            or_(by_name, User.steam_id == needle) if _STEAM_ID.fullmatch(needle) else by_name
        )
    if cursor is not None:
        stamp, last_id = decode_cursor(cursor)
        stmt = stmt.where(
            or_(User.created_at < stamp, and_(User.created_at == stamp, User.id < last_id))
        )
    rows = list((await db.execute(stmt)).all())
    page, more = rows[:limit], len(rows) > limit
    items = [
        AdminUserRow(
            id=u.id,
            display_name=u.display_name,
            avatar_url=u.avatar_url,
            steam_id=u.steam_id,
            roles=list(u.roles),
            banned_at=u.banned_at,
            created_at=u.created_at,
            balance_uzs=wire_uzs(Decimal(b)),
            api_key=None
            if key_id is None
            else AdminUserKeyBrief(id=key_id, pricing_profile=profile),
        )
        for u, b, key_id, profile in page
    ]
    last = page[-1][0] if more else None
    return items, (encode_cursor(last.created_at, last.id) if last is not None else None)


async def _topups(db: AsyncSession, user_id: str) -> list[AdminTopupOut]:
    """The latest top-ups; the provider is the paid attempt's, else the first attempt's."""
    paid = select(Payment.provider).where(Payment.id == WalletTopup.payment_id)
    first = (
        select(Payment.provider)
        .where(Payment.topup_id == WalletTopup.id)
        .order_by(Payment.created_at, Payment.id)
        .limit(1)
    )
    provider = func.coalesce(paid.scalar_subquery(), first.scalar_subquery()).label("provider")
    rows = await db.execute(
        select(WalletTopup, provider)
        .where(WalletTopup.user_id == user_id)
        .order_by(WalletTopup.created_at.desc(), WalletTopup.id.desc())
        .limit(CARD_ROWS)
    )
    return [
        AdminTopupOut(
            number=t.number,
            amount_uzs=wire_uzs(t.amount_uzs),
            status=t.status,
            provider=p,
            created_at=t.created_at,
            succeeded_at=t.succeeded_at,
        )
        for t, p in rows
    ]


async def user_card(db: AsyncSession, user: User) -> AdminUserCard:
    """The user page: profile, balance, the latest 20 ledger lines, top-ups and orders."""
    entries = await entries_for_admin(db, user.id, limit=CARD_ROWS)
    usd_entries = await entries_for_admin(db, user.id, limit=CARD_ROWS, currency="USD")
    return AdminUserCard(
        user=AdminUserDetail.of(user),
        balance_uzs=wire_uzs(await user_balance(db, user.id)),
        entries=[AdminEntryOut.of(e) for e in entries],
        topups=await _topups(db, user.id),
        orders=await recent_orders(db, user.id),
        usd_wallet_enabled=user.usd_wallet_enabled,
        balance_usd=wire_usd(await user_usd_balance(db, user.id)),
        usd_entries=[AdminEntryOut.of(e, "USD") for e in usd_entries],
        api_key_id=await db.scalar(
            select(ApiKey.id)
            .where(ApiKey.user_id == user.id)
            .order_by(ApiKey.created_at.desc())
            .limit(1)
        ),
    )


# --- idempotent replay ------------------------------------------------------------------


async def replayed(
    db: AsyncSession, *, scope: str, key: str, request: dict[str, Any]
) -> dict[str, Any] | None:
    """The stored response for ``key`` when it was used for this very request.

    The replay row keeps the request it answered, so a key reused for another body (or
    another user) is told apart instead of replaying the wrong answer.

    Raises:
        ConflictError: ``code="idempotency_mismatch"`` — the key answered another request.
    """
    hit = await load_replay(db, scope=scope, idempotency_key=key)
    if hit is None:
        return None
    stored = hit.body or {}
    if stored.get("request") != request:
        raise ConflictError(
            "this Idempotency-Key was used for another request", code="idempotency_mismatch"
        )
    response: dict[str, Any] = stored["response"]
    return response


async def remember(
    db: AsyncSession,
    *,
    scope: str,
    key: str,
    request: dict[str, Any],
    response: dict[str, Any],
) -> None:
    """Store ``response`` as the answer to ``request`` under ``key``."""
    await save_replay(
        db, scope=scope, idempotency_key=key, body={"request": request, "response": response}
    )


# --- writes -----------------------------------------------------------------------------


async def ban(db: AsyncSession, *, admin: User, user: User, reason: str) -> None:
    """Suspend ``user`` and sign them out everywhere; audited ``users.ban``.

    Raises:
        ConflictError: ``ban_self``, ``ban_admin`` or ``already_banned``.
    """
    if user.id == admin.id:
        raise ConflictError("you cannot ban yourself", code="ban_self")
    if has_role(user, "admin"):
        raise ConflictError("an admin cannot be banned; revoke the role first", code="ban_admin")
    if user.banned_at is not None:
        raise ConflictError("the account is already banned", code="already_banned")
    stamp = now()
    user.banned_at = stamp
    user.ban_reason = reason
    user.updated_at = stamp
    await revoke_all_sessions(db, user.id)
    await record(
        db,
        actor_id=admin.id,
        action="users.ban",
        target_type="user",
        target_id=user.id,
        payload={"reason": reason},
    )


async def unban(db: AsyncSession, *, admin: User, user: User, reason: str) -> None:
    """Lift the suspension (the user signs in again); audited ``users.unban``.

    Raises:
        ConflictError: ``not_banned``.
    """
    if user.banned_at is None:
        raise ConflictError("the account is not banned", code="not_banned")
    user.banned_at = None
    user.ban_reason = None
    user.updated_at = now()
    await record(
        db,
        actor_id=admin.id,
        action="users.unban",
        target_type="user",
        target_id=user.id,
        payload={"reason": reason},
    )


async def adjust(
    db: AsyncSession, *, admin: User, user: User, amount: int, reason: str, key: str
) -> None:
    """Credit or claw back ``amount`` soʻm through the ledger; audited ``wallet.adjust``.

    Raises:
        InsufficientBalanceError: ``balance_too_low`` — a clawback below zero (R13).
        ConflictError: ``idempotency_mismatch`` — the ledger key booked another adjustment.
    """
    await admin_adjust(
        db,
        user_id=user.id,
        amount=Decimal(amount),
        reason=reason,
        admin_id=admin.id,
        idempotency_key=key,
    )
    await record(
        db,
        actor_id=admin.id,
        action="wallet.adjust",
        target_type="user",
        target_id=user.id,
        payload={"amount_uzs": amount, "reason": reason},
    )


async def adjust_usd(
    db: AsyncSession, *, admin: User, user: User, units: int, reason: str, key: str
) -> None:
    """Credit or claw back ``units`` milli-USD; audited ``wallet.adjust_usd``.

    Raises:
        InsufficientBalanceError: ``balance_too_low`` — a clawback below zero.
        ConflictError: ``idempotency_mismatch`` — the ledger key booked another adjustment.
    """
    await admin_adjust_usd(
        db,
        user_id=user.id,
        amount=Decimal(units),
        reason=reason,
        admin_id=admin.id,
        idempotency_key=key,
    )
    await record(
        db,
        actor_id=admin.id,
        action="wallet.adjust_usd",
        target_type="user",
        target_id=user.id,
        payload={"amount_usd": wire_usd(units), "reason": reason},
    )


async def switch_usd(
    db: AsyncSession, *, admin: User, user: User, enabled: bool, reason: str
) -> None:
    """Turn the USD wallet on or off; audited ``wallet.usd_switch``.

    Switching off with a non-zero dollar balance is allowed: the money stays on the
    account, conversion and API purchases stop until it is switched on again.
    """
    user.usd_wallet_enabled = enabled
    user.updated_at = now()
    await record(
        db,
        actor_id=admin.id,
        action="wallet.usd_switch",
        target_type="user",
        target_id=user.id,
        payload={"enabled": enabled, "reason": reason},
    )


__all__ = [
    "CARD_ROWS",
    "adjust",
    "adjust_usd",
    "ban",
    "get_user",
    "list_users",
    "remember",
    "replayed",
    "switch_usd",
    "unban",
    "user_card",
]
