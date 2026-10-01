"""What the trade sweeps share (``orders.sweeps``, ``orders.trade_audit``): the row read
before Waxpeer is asked, the locked re-read, and the chunked lookup.
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.logging import get_logger
from csmarket.modules.orders.models import Order, SkinTrade
from csmarket.modules.skins.api import (
    LOOKUP_MAX_IDS,
    TradeClient,
    WaxpeerError,
    WaxpeerTrade,
    WaxpeerUnavailableError,
)

log = get_logger("csmarket.orders.sweeps")

#: A lookup failure: nothing is decided on it (403 and 429 are subclasses).
LOOKUP_ERRORS = (WaxpeerError, WaxpeerUnavailableError)


class SweepRow(BaseModel):
    """An order and its trade's lookup key, read before Waxpeer is asked."""

    model_config = ConfigDict(frozen=True)

    order_id: str
    project_id: str
    buy_pending: bool = False


async def lock_both(db: AsyncSession, order_id: str) -> tuple[Order | None, SkinTrade | None]:
    """The order, then its trade, ``FOR UPDATE`` (ruling K), read fresh."""
    order = await db.scalar(
        select(Order)
        .where(Order.id == order_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    trade = await db.scalar(
        select(SkinTrade)
        .where(SkinTrade.order_id == order_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return order, trade


async def lookup(client: TradeClient, project_ids: Sequence[str]) -> list[WaxpeerTrade]:
    """Every trade under ``project_ids``, asked at most :data:`LOOKUP_MAX_IDS` at a time."""
    found: list[WaxpeerTrade] = []
    for start in range(0, len(project_ids), LOOKUP_MAX_IDS):
        found += await client.check_project_ids(list(project_ids[start : start + LOOKUP_MAX_IDS]))
    return found


def of_project(found: Sequence[WaxpeerTrade], project_id: str) -> list[WaxpeerTrade]:
    """The trades of one ``project_id``."""
    return [t for t in found if t.project_id == project_id]


def crashed(event: str, order_id: str, exc: Exception) -> None:
    """One order's failure: its type only (an error's text can carry SQL parameters)."""
    log.error(event, order_id=order_id, error=type(exc).__name__)


__all__ = ["LOOKUP_ERRORS", "SweepRow", "crashed", "lock_both", "lookup", "of_project"]
