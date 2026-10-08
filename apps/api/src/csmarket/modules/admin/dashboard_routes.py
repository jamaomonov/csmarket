"""``GET /api/v1/admin/dashboard`` — today / 7 / 30 Tashkent days at a glance (M4b R9)."""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.api.v1.deps import db_session
from csmarket.core.clock import now
from csmarket.core.errors import ValidationError
from csmarket.core.redis import get_redis
from csmarket.modules.admin.dashboard_schemas import DashboardOut
from csmarket.modules.admin.deps import require_admin
from csmarket.modules.orders.api import Days, dashboard_summary
from csmarket.modules.sales.api import payouts_summary

_WINDOWS = frozenset({1, 7, 30})

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


@router.get("/dashboard", response_model=DashboardOut, summary="The dashboard")
async def dashboard(
    db: Annotated[AsyncSession, Depends(db_session)],
    days: Annotated[int, Query(description="1 (today), 7 or 30 Tashkent days")] = 1,
) -> DashboardOut:
    """Sales, margin and refunds by Tashkent day, orders in flight, open attentions and the
    last Waxpeer balance read. Reads only. Any ``days`` but 1, 7 or 30 is 422 ``dashboard_days``.
    """
    if days not in _WINDOWS:
        raise ValidationError("days must be 1, 7 or 30", code="dashboard_days")
    window = cast("Days", days)
    summary = await dashboard_summary(db, get_redis(), days=window, at=now())
    return DashboardOut.of(summary, await payouts_summary(db))
