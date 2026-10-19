"""«Продано в минус»: delivered orders of a window sold below what their market charged.

A normal buy cannot lose — the worker never pays more than the cost agreed at checkout — so a
row here means a manual price rule, a market keeping money for a failed trade, or a partner
key priced at cost. An empty list is the normal day.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.modules.analytics.fmt import dec, som
from csmarket.modules.analytics.lines import order_lines
from csmarket.modules.analytics.schemas import LossesOut, LossOut
from csmarket.modules.analytics.window import Channel, Window

LIMIT = 200


async def losses(db: AsyncSession, w: Window, channel: Channel) -> LossesOut:
    """The window's delivered orders with a negative profit, worst first."""
    lines = order_lines(w, channel)
    rows = await db.execute(
        select(
            lines.c.number,
            lines.c.name,
            lines.c.source,
            lines.c.paid_at,
            lines.c.revenue_uzs,
            lines.c.cost_uzs,
            lines.c.profit_uzs,
        )
        .where(lines.c.earned, lines.c.profit_uzs < 0)
        .order_by(lines.c.profit_uzs, lines.c.number)
        .limit(LIMIT)
    )
    return LossesOut(
        items=[
            LossOut(
                number=number,
                name=name,
                source=source,
                paid_at=paid_at,
                revenue_uzs=som(dec(rev)),
                cost_uzs=som(dec(cost)),
                profit_uzs=som(dec(profit)),
            )
            for number, name, source, paid_at, rev, cost, profit in rows.all()
        ]
    )


__all__ = ["LIMIT", "losses"]
