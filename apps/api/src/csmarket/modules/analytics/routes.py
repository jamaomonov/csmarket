"""``/api/v1/admin/analytics/*`` — the admin «Аналитика» page (spec 2026-10-19-analytics).

Admin only, reads only (no ``Idempotency-Key``: nothing is written). ``since`` / ``until`` are
Tashkent dates, ``until`` inclusive, at most 366 days (422 ``analytics_window``); ``month`` is
``YYYY-MM`` (422 ``analytics_month``); ``channel`` is ``all``, ``site`` or ``api``. Answers are
cached 2 minutes, an hour once the window ended more than 8 days ago.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.api.v1.deps import db_session
from csmarket.core.clock import now
from csmarket.core.redis import get_redis
from csmarket.modules.admin.api import require_admin
from csmarket.modules.analytics import service
from csmarket.modules.analytics.schemas import BusinessOut, CalendarOut, LossesOut
from csmarket.modules.analytics.window import Channel, month_window, parse_window
from csmarket.modules.orders.api import TASHKENT

router = APIRouter(prefix="/admin/analytics", tags=["admin"], dependencies=[Depends(require_admin)])

Db = Annotated[AsyncSession, Depends(db_session, scope="function")]
Since = Annotated[date, Query(description="First Tashkent day")]
Until = Annotated[date, Query(description="Last Tashkent day, included")]


def _today() -> date:
    return now().astimezone(TASHKENT).date()


@router.get("/business", response_model=BusinessOut, summary="Analytics: a period")
async def get_business(db: Db, since: Since, until: Until, channel: Channel = "all") -> BusinessOut:
    """Totals against the previous period of the same length, the days, and every block:
    markets, channels, payments and kassa fees, categories, top skins, buyers, refunds,
    buy-back. Profit = price − what the market charged, in soʻm at the order's CBU rate."""
    window = parse_window(since, until)
    return await service.business(db, get_redis(), window, channel, _today())


@router.get("/calendar", response_model=CalendarOut, summary="Analytics: a month by day")
async def get_calendar(
    db: Db, month: Annotated[str, Query(max_length=7)], channel: Channel = "all"
) -> CalendarOut:
    """Every day of ``month``: orders, revenue, earned and in-flight profit, buy-back."""
    return await service.calendar(db, get_redis(), month_window(month), channel, _today())


@router.get("/losses", response_model=LossesOut, summary="Analytics: sold below cost")
async def get_losses(db: Db, since: Since, until: Until, channel: Channel = "all") -> LossesOut:
    """«Продано в минус»: delivered orders of the window with a negative profit, worst first
    (at most 200)."""
    return await service.losses_of(db, get_redis(), parse_window(since, until), channel, _today())


__all__ = ["router"]
