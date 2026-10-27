"""«Партнёрам»: what partners were credited in the window, beside gross profit
(spec 2026-10-27-referrals, owner ruling 7)."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from csmarket.modules.analytics.business import totals
from csmarket.modules.analytics.window import parse_window
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.referrals_factory import make_partner, make_reward
from tests.integration.reviews_factory import delivered_order

pytestmark = pytest.mark.asyncio

OCT_9_10 = parse_window(date(2026, 10, 9), date(2026, 10, 10))


async def _reward(db: AsyncSession, *, status: str, credited_at: datetime | None) -> None:
    partner = await make_partner(db)
    order = await delivered_order(db)
    await make_reward(
        db,
        partner=partner,
        order=order,
        status=status,
        amount_uzs=1000,
        credited_at=credited_at,
    )


async def test_partners_line_counts_credited_in_window_only(db_session: AsyncSession) -> None:
    await _reward(db_session, status="credited", credited_at=datetime(2026, 10, 9, 12, tzinfo=UTC))
    await _reward(db_session, status="credited", credited_at=datetime(2026, 10, 12, tzinfo=UTC))
    await _reward(db_session, status="held", credited_at=None)
    await _reward(db_session, status="cancelled", credited_at=None)
    head = await totals(db_session, OCT_9_10, "all")
    assert head.partners_uzs == "1000"
    site = await totals(db_session, OCT_9_10, "site")
    assert site.partners_uzs == "1000"


async def test_api_channel_has_none(db_session: AsyncSession) -> None:
    await _reward(db_session, status="credited", credited_at=datetime(2026, 10, 9, 12, tzinfo=UTC))
    assert (await totals(db_session, OCT_9_10, "api")).partners_uzs == "0"
