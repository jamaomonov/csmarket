"""``GET /api/v1/admin/sales/reconciliation`` — «Сверка»: each sale's quoted vs credited
Skinslink amount (spec 2026-10-13-sales-pnl). Admin only, reads only; mounted before
:mod:`.admin_routes` so ``reconciliation`` never reads as a sale number.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, cast

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.api.v1.deps import db_session
from csmarket.core.clock import now
from csmarket.core.errors import ValidationError
from csmarket.modules.admin.api import require_admin
from csmarket.modules.orders.api import Days
from csmarket.modules.sales.pnl import ReconFlag
from csmarket.modules.sales.pnl_query import Recon, reconciliation

router = APIRouter(prefix="/admin/sales", tags=["admin"], dependencies=[Depends(require_admin)])

_WINDOWS = frozenset({1, 7, 30})


def _plain(value: Decimal | None) -> str | None:
    return None if value is None else format(value.normalize(), "f")


class ReconRowOut(BaseModel):
    number: str
    status: str
    #: When Skinslink completed it (``null`` for an open revert that never completed).
    done_at: datetime | None
    trade_id: int | None
    quoted_usd: str
    amount_usd: str | None
    #: ``amount_usd − quoted_usd``; ``null`` with no amount.
    diff_usd: str | None
    flag: ReconFlag | None


class ReconOut(BaseModel):
    items: list[ReconRowOut]
    next_cursor: str | None
    #: Over the whole window, whatever the page and the filter.
    expected_usd: str
    credited_usd: str
    diff_usd: str
    problems: int

    @classmethod
    def of(cls, r: Recon) -> ReconOut:
        """Strings for the money."""
        return cls(
            items=[
                ReconRowOut(
                    number=i.number,
                    status=i.status,
                    done_at=i.done_at,
                    trade_id=i.trade_id,
                    quoted_usd=_plain(i.quoted_usd) or "0",
                    amount_usd=_plain(i.amount_usd),
                    diff_usd=_plain(None if i.amount_usd is None else i.amount_usd - i.quoted_usd),
                    flag=i.flag,
                )
                for i in r.items
            ],
            next_cursor=r.next_cursor,
            expected_usd=_plain(r.expected_usd) or "0",
            credited_usd=_plain(r.credited_usd) or "0",
            diff_usd=_plain(r.credited_usd - r.expected_usd) or "0",
            problems=r.problems,
        )


@router.get("/reconciliation", response_model=ReconOut, summary="Skinslink reconciliation")
async def get_reconciliation(
    db: Annotated[AsyncSession, Depends(db_session, scope="function")],
    days: Annotated[int, Query(description="1 (today), 7 or 30 Tashkent days")] = 7,
    problems: Annotated[bool, Query(description="Only the flagged sales")] = False,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
) -> ReconOut:
    """Sales Skinslink completed in the window (and any open revert): quoted, credited, the
    difference and a flag — ``short`` (under 99 % of the quote), ``missing`` (completed with no
    amount) or ``reverted``. Any ``days`` but 1, 7 or 30 is 422 ``dashboard_days``."""
    if days not in _WINDOWS:
        raise ValidationError("days must be 1, 7 or 30", code="dashboard_days")
    recon = await reconciliation(
        db, days=cast("Days", days), at=now(), problems=problems, cursor=cursor
    )
    return ReconOut.of(recon)
