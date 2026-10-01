"""``/api/v1/admin/payments`` — find a payment, open it with the kassas' transactions.

Admin only (``require_admin`` on the whole router); read-only, so no ``Idempotency-Key``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.api.v1.deps import db_session
from csmarket.modules.admin import payments_service as svc
from csmarket.modules.admin.deps import require_admin
from csmarket.modules.admin.payments_schemas import (
    AdminPaymentDetail,
    AdminPaymentsOut,
    PaymentStatus,
    Provider,
    Purpose,
)

router = APIRouter(prefix="/admin/payments", tags=["admin"], dependencies=[Depends(require_admin)])

Db = Annotated[AsyncSession, Depends(db_session)]


@router.get("", response_model=AdminPaymentsOut, summary="Find payments")
async def list_payments(
    db: Db,
    *,
    q: Annotated[str | None, Query(max_length=32)] = None,
    status: PaymentStatus | None = None,
    provider: Provider | None = None,
    purpose: Purpose | None = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> AdminPaymentsOut:
    """Newest first; ``q`` = a full or partial number (any case), matched from the start."""
    items, next_cursor = await svc.list_payments(
        db, q=q, status=status, provider=provider, purpose=purpose, cursor=cursor, limit=limit
    )
    return AdminPaymentsOut(items=items, next_cursor=next_cursor)


@router.get("/{payment_id}", response_model=AdminPaymentDetail, summary="A payment")
async def get_payment(payment_id: str, db: Db) -> AdminPaymentDetail:
    """The attempt, its top-up and every transaction the kassas hold for it."""
    return await svc.payment_detail(db, payment_id)


__all__ = ["router"]
