"""The admin's «Продажи» and «Настройки выкупа» (spec 2026-10-08 §7).

A page of rows loads its users in one query. A settings save affects new sales only (each
sale keeps its own numbers) and is audited ``sales.settings.save`` in the caller's
transaction.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from decimal import Decimal

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.config import get_settings
from csmarket.core.cursor import decode_cursor, encode_cursor
from csmarket.core.errors import NotFoundError
from csmarket.core.money import wire_uzs
from csmarket.core.redis import get_redis
from csmarket.modules.admin.api import AuditPayload, record
from csmarket.modules.fx.api import current_usd_uzs
from csmarket.modules.sales.admin_schemas import (
    AdminSaleItemOut,
    AdminSaleOut,
    AdminSaleRowOut,
    AdminSalesPageOut,
    AdminUserOut,
    PayoutRowOut,
    SaleSettingsOut,
)
from csmarket.modules.sales.cards import masked
from csmarket.modules.sales.models import PayoutCard, PayoutRequest, Sale, SaleItem
from csmarket.modules.sales.rules import SaleSettings
from csmarket.modules.sales.schemas import SaleStatusOut, plain
from csmarket.modules.sales.settings_store import (
    read_sale_settings,
    save_sale_settings,
    settings_row,
)
from csmarket.modules.sales.views import bonus_fee
from csmarket.modules.users.api import User


async def users_by_id(db: AsyncSession, ids: Iterable[str]) -> dict[str, AdminUserOut]:
    """``id → AdminUserOut`` for ``ids``, one query."""
    wanted = set(ids)
    if not wanted:
        return {}
    rows = await db.execute(select(User.id, User.display_name).where(User.id.in_(wanted)))
    return {uid: AdminUserOut(id=uid, display_name=name) for uid, name in rows.all()}


def user_of(users: dict[str, AdminUserOut], uid: str) -> AdminUserOut:
    """``uid``'s row (a bare id if the users table no longer names it)."""
    return users.get(uid) or AdminUserOut(id=uid, display_name=None)


def payout_row(
    request: PayoutRequest, *, number: str, card: PayoutCard, user: AdminUserOut
) -> PayoutRowOut:
    """A request as the queue shows it."""
    return PayoutRowOut(
        id=request.id,
        sale_number=number,
        user=user,
        card_type=card.type,  # type: ignore[arg-type]  # the column's check
        card_masked=masked(card.last4),
        amount_uzs=wire_uzs(request.amount_uzs),
        fee_uzs=wire_uzs(request.fee_uzs),
        status=request.status,  # type: ignore[arg-type]
        to_pay_at=request.to_pay_at,
        paid_at=request.paid_at,
        created_at=request.created_at,
    )


def sale_row(sale: Sale, user: AdminUserOut) -> AdminSaleRowOut:
    """A sale as the list shows it."""
    return AdminSaleRowOut(
        number=sale.number,
        status=sale.status,  # type: ignore[arg-type]
        user=user,
        payout_to=sale.payout_to,  # type: ignore[arg-type]
        quoted_usd=plain(sale.quoted_usd),
        payout_uzs=wire_uzs(sale.payout_uzs),
        margin_usd=plain(sale.margin_usd),
        attention_reason=sale.attention_reason,
        created_at=sale.created_at,
    )


async def sale_admin_out(db: AsyncSession, sale: Sale) -> AdminSaleOut:
    """A sale's full page."""
    items = (
        await db.scalars(
            select(SaleItem).where(SaleItem.sale_id == sale.id).order_by(SaleItem.asset_id)
        )
    ).all()
    card = await db.get(PayoutCard, sale.payout_card_id) if sale.payout_card_id else None
    request = await db.scalar(select(PayoutRequest).where(PayoutRequest.sale_id == sale.id))
    users = await users_by_id(db, [sale.user_id])
    user = user_of(users, sale.user_id)
    bonus, fee = bonus_fee(sale)
    return AdminSaleOut(
        number=sale.number,
        status=sale.status,  # type: ignore[arg-type]
        user=user,
        payout_to=sale.payout_to,  # type: ignore[arg-type]
        card_type=card.type if card else None,  # type: ignore[arg-type]
        card_masked=masked(card.last4) if card else None,
        quoted_usd=plain(sale.quoted_usd),
        amount_usd=plain(sale.amount_usd) if sale.amount_usd is not None else None,
        items_uzs=wire_uzs(sale.items_uzs),
        bonus_uzs=wire_uzs(bonus),
        fee_uzs=wire_uzs(fee),
        payout_uzs=wire_uzs(sale.payout_uzs),
        rate=plain(sale.rate),
        margin_usd=plain(sale.margin_usd),
        trade_id=sale.trade_id,
        trade_offer_id=sale.trade_offer_id,
        bot_name=sale.bot_name,
        offer_expiry_at=sale.offer_expiry_at,
        hold_end_at=sale.hold_end_at,
        fail_reason=sale.fail_reason,
        attention_reason=sale.attention_reason,
        credited_at=sale.credited_at,
        created_at=sale.created_at,
        updated_at=sale.updated_at,
        items=[
            AdminSaleItemOut(
                asset_id=i.asset_id,
                name=i.name,
                price_usd=plain(i.price_usd),
                price_uzs=wire_uzs(i.price_uzs),
            )
            for i in items
        ],
        payout=payout_row(request, number=sale.number, card=card, user=user)
        if request is not None and card is not None
        else None,
    )


async def sale_by_number(db: AsyncSession, number: str) -> AdminSaleOut:
    """Sale ``number``'s page.

    Raises:
        NotFoundError: Unknown.
    """
    sale = await db.scalar(
        select(Sale).where(Sale.number == number).execution_options(populate_existing=True)
    )
    if sale is None:
        raise NotFoundError("sale not found")
    return await sale_admin_out(db, sale)


async def list_sales_admin(
    db: AsyncSession,
    *,
    status: SaleStatusOut | None,
    q: str | None,
    cursor: str | None,
    limit: int,
) -> AdminSalesPageOut:
    """Sales newest first; ``q`` is a number prefix in any case."""
    stmt = select(Sale).order_by(Sale.created_at.desc(), Sale.id.desc()).limit(limit + 1)
    if status is not None:
        stmt = stmt.where(Sale.status == status)
    if q:
        stmt = stmt.where(Sale.number.startswith(q.strip().upper(), autoescape=True))
    if cursor is not None:
        stamp, sale_id = decode_cursor(cursor)
        stmt = stmt.where(
            or_(Sale.created_at < stamp, and_(Sale.created_at == stamp, Sale.id < sale_id))
        )
    found = list((await db.scalars(stmt)).all())
    page = found[:limit]
    users = await users_by_id(db, (s.user_id for s in page))
    next_cursor = encode_cursor(page[-1].created_at, page[-1].id) if len(found) > limit else None
    return AdminSalesPageOut(
        items=[sale_row(s, user_of(users, s.user_id)) for s in page], next_cursor=next_cursor
    )


async def settings_view(db: AsyncSession) -> SaleSettingsOut:
    """The saved document, who saved it and when, and the CBU rate now."""
    row = await settings_row(db)
    users = await users_by_id(db, [row.updated_by] if row and row.updated_by else [])
    fx = await current_usd_uzs(
        db, get_redis(), max_age_days=get_settings().fx_max_age_days, uplift_pct=Decimal(0)
    )
    return SaleSettingsOut(
        settings=await read_sale_settings(db),
        updated_at=row.updated_at if row else None,
        updated_by=user_of(users, row.updated_by) if row and row.updated_by else None,
        rate_uzs=plain(fx.rate) if fx is not None else None,
    )


def _diff(before: SaleSettings, after: SaleSettings) -> AuditPayload:
    """Every changed field as ``"<old JSON> -> <new JSON>"`` (an audit payload is flat)."""
    old, new = before.model_dump(mode="json"), after.model_dump(mode="json")
    changed: AuditPayload = {
        k: f"{json.dumps(old[k])} -> {json.dumps(v)}" for k, v in new.items() if old[k] != v
    }
    return changed or {"unchanged": "true"}


async def save_settings(db: AsyncSession, *, doc: SaleSettings, admin_id: str) -> None:
    """Replace the document; audited ``sales.settings.save``. Flushes, never commits."""
    before = await read_sale_settings(db)
    await save_sale_settings(db, settings=doc, admin_id=admin_id)
    await record(
        db,
        actor_id=admin_id,
        action="sales.settings.save",
        target_type="sale_settings",
        target_id="1",
        payload=_diff(before, doc),
    )


__all__ = [
    "list_sales_admin",
    "payout_row",
    "sale_admin_out",
    "sale_by_number",
    "sale_row",
    "save_settings",
    "settings_view",
    "user_of",
    "users_by_id",
]
