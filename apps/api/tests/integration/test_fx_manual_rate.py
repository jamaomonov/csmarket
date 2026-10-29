"""``POST /admin/fx/rate``: the admin sets the CBU rate by hand when no source answers."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from decimal import Decimal

import pytest
from csmarket.core.redis import get_redis
from csmarket.modules.admin.models import AdminAuditLog
from csmarket.modules.fx.service import current_usd_uzs
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

Headers = Callable[[], Awaitable[dict[str, str]]]
URL = "/api/v1/admin/fx/rate"
KEY = {"Idempotency-Key": "fx-manual-key-000001"}


async def test_sets_the_rate_caches_it_and_audits(
    integration_client: AsyncClient, db_session: AsyncSession, admin_headers: Headers
) -> None:
    r = await integration_client.post(
        URL, json={"usd_uzs": "12004.02"}, headers=(await admin_headers()) | KEY
    )
    assert r.status_code == 201, r.text
    assert (r.json()["usd_uzs"], r.json()["source"]) == ("12004.02", "manual")
    rate = await current_usd_uzs(db_session, get_redis(), max_age_days=7, uplift_pct=Decimal(0))
    assert rate is not None
    assert (rate.rate, rate.source) == (Decimal("12004.02"), "manual")
    audits = await db_session.scalar(
        select(func.count())
        .select_from(AdminAuditLog)
        .where(AdminAuditLog.action == "fx.rate.manual")
    )
    assert audits == 1
    again = await integration_client.post(
        URL, json={"usd_uzs": "12004.02"}, headers=(await admin_headers()) | KEY
    )
    assert again.json()["id"] == r.json()["id"]


@pytest.mark.parametrize("value", ["0", "999", "100001", "abc"])
async def test_an_implausible_rate_is_422(
    integration_client: AsyncClient, admin_headers: Headers, value: str
) -> None:
    r = await integration_client.post(
        URL, json={"usd_uzs": value}, headers=(await admin_headers()) | KEY
    )
    assert r.status_code == 422


async def test_customers_are_refused(
    integration_client: AsyncClient, customer_headers: Headers
) -> None:
    r = await integration_client.post(
        URL, json={"usd_uzs": "12004.02"}, headers=(await customer_headers()) | KEY
    )
    assert r.status_code == 403
