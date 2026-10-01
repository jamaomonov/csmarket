"""Admin payments: search the attempts, open one with its top-up or order and the kassas' rows.

Read-only. A list is one statement whatever its size (the payer's name comes from a join);
a detail is a fixed handful (payment, top-up or order, one lookup per kassa).
"""

from __future__ import annotations

import uuid

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.cursor import decode_cursor, encode_cursor
from csmarket.core.errors import NotFoundError
from csmarket.core.money import wire_uzs
from csmarket.modules.admin.payments_kassa import kassa_transactions
from csmarket.modules.admin.payments_schemas import (
    AdminOrderInfo,
    AdminPaymentDetail,
    AdminPaymentFull,
    AdminPaymentRow,
    AdminPaymentUser,
    AdminTopupInfo,
)
from csmarket.modules.orders.api import Order
from csmarket.modules.payments.api import Payment, WalletTopup
from csmarket.modules.users.api import User


def _like_escape(needle: str) -> str:
    return needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _row_fields(payment: Payment, display_name: str | None) -> dict[str, object]:
    return {
        "id": payment.id,
        "number": payment.number,
        "purpose": payment.purpose,
        "provider": payment.provider,
        "amount_uzs": wire_uzs(payment.amount_uzs),
        "status": payment.status,
        "created_at": payment.created_at,
        "succeeded_at": payment.succeeded_at,
        "user": AdminPaymentUser(id=payment.user_id, display_name=display_name),
    }


async def list_payments(
    db: AsyncSession,
    *,
    q: str | None,
    status: str | None,
    provider: str | None,
    purpose: str | None,
    cursor: str | None,
    limit: int,
) -> tuple[list[AdminPaymentRow], str | None]:
    """Payments newest first, keyset on ``(created_at DESC, id DESC)``.

    ``q`` is a full or partial number (any case): a prefix match on ``number``, with ``%``
    and ``_`` literal. Filters combine with AND.
    """
    stmt = (
        select(Payment, User.display_name)
        .join(User, User.id == Payment.user_id)
        .order_by(Payment.created_at.desc(), Payment.id.desc())
        .limit(limit + 1)
    )
    if needle := (q or "").strip().upper():
        stmt = stmt.where(Payment.number.like(f"{_like_escape(needle)}%", escape="\\"))
    if status is not None:
        stmt = stmt.where(Payment.status == status)
    if provider is not None:
        stmt = stmt.where(Payment.provider == provider)
    if purpose is not None:
        stmt = stmt.where(Payment.purpose == purpose)
    if cursor is not None:
        stamp, last_id = decode_cursor(cursor)
        stmt = stmt.where(
            or_(Payment.created_at < stamp, and_(Payment.created_at == stamp, Payment.id < last_id))
        )
    rows = list((await db.execute(stmt)).all())
    page, more = rows[:limit], len(rows) > limit
    items = [AdminPaymentRow.model_validate(_row_fields(p, name)) for p, name in page]
    last = page[-1][0] if more else None
    return items, (encode_cursor(last.created_at, last.id) if last is not None else None)


async def payment_detail(db: AsyncSession, payment_id: str) -> AdminPaymentDetail:
    """One payment with its payer, its top-up or order, and the kassas' transactions.

    Raises:
        NotFoundError: no such payment, or ``payment_id`` is not a UUID.
    """
    try:
        uuid.UUID(payment_id)
    except ValueError as exc:
        raise NotFoundError("payment not found") from exc
    found = (
        await db.execute(
            select(Payment, User.display_name)
            .join(User, User.id == Payment.user_id)
            .where(Payment.id == payment_id)
        )
    ).one_or_none()
    if found is None:
        raise NotFoundError("payment not found")
    payment, display_name = found
    topup = await db.get(WalletTopup, payment.topup_id) if payment.topup_id is not None else None
    order = await db.get(Order, payment.order_id) if payment.order_id is not None else None
    metadata = {
        k: v
        for k, v in payment.extra_metadata.items()
        if v is None or isinstance(v, str | int | bool)
    }
    return AdminPaymentDetail(
        payment=AdminPaymentFull.model_validate(
            {
                **_row_fields(payment, display_name),
                "provider_ref": payment.provider_ref,
                "metadata": metadata,
            }
        ),
        topup=(
            AdminTopupInfo(
                number=topup.number,
                amount_uzs=wire_uzs(topup.amount_uzs),
                status=topup.status,  # type: ignore[arg-type]  # DB check constraint
                expires_at=topup.expires_at,
                succeeded_at=topup.succeeded_at,
            )
            if topup is not None
            else None
        ),
        order=(
            AdminOrderInfo(
                number=order.number,
                status=order.status,  # type: ignore[arg-type]  # DB check constraint
                price_uzs=wire_uzs(order.price_uzs),
            )
            if order is not None
            else None
        ),
        kassa=await kassa_transactions(db, payment.id),
    )


__all__ = ["list_payments", "payment_detail"]
