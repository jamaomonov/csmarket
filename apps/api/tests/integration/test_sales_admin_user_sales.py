"""The user page's «Продажи»: ``GET /admin/sales/users/{user_id}`` — the user's latest sales
with their skins, and the totals of what reached us."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.payments_factory import make_user
from tests.integration.sales_factory import make_sale

pytestmark = pytest.mark.asyncio

Headers = Callable[[], Awaitable[dict[str, str]]]
BASE = "/api/v1/admin/sales/users"
T0 = datetime(2026, 10, 1, 10, 0, tzinfo=UTC)


async def test_the_user_page_lists_the_sales_with_their_skins_and_the_totals(
    db_session: AsyncSession, integration_client: AsyncClient, admin_headers: Headers
) -> None:
    headers = await admin_headers()
    seller = await make_user(db_session)
    statuses = ("closed", "hold", "reverted", "offered")
    made = [
        await make_sale(
            db_session,
            user=seller,
            status=status,
            payout_uzs=Decimal(10_000 * (i + 1)),
            created_at=T0 + timedelta(minutes=i),
        )
        for i, status in enumerate(statuses)
    ]
    await make_sale(db_session, status="closed")  # someone else's
    r = await integration_client.get(f"{BASE}/{seller.id}", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert [s["number"] for s in body["items"]] == [s.number for s in made[::-1]]
    # ``closed`` and ``hold`` reached us; a reverted or merely offered sale did not.
    assert (body["sold_count"], body["sold_uzs"]) == (2, "30000")
    assert body["items"][0]["items"] == [
        {"name": "AK-47 | Redline (Field-Tested)", "image_url": None},
        {"name": "P250 | Sand Dune (Field-Tested)", "image_url": None},
    ]
    assert body["items"][0]["user"]["id"] == seller.id


async def test_a_user_who_never_sold_has_an_empty_page(
    db_session: AsyncSession, integration_client: AsyncClient, admin_headers: Headers
) -> None:
    headers = await admin_headers()
    user = await make_user(db_session)
    r = await integration_client.get(f"{BASE}/{user.id}", headers=headers)
    assert r.json() == {"sold_count": 0, "sold_uzs": "0", "items": []}


async def test_the_user_sales_are_admin_only(
    db_session: AsyncSession, integration_client: AsyncClient, customer_headers: Headers
) -> None:
    user = await make_user(db_session)
    r = await integration_client.get(f"{BASE}/{user.id}", headers=await customer_headers())
    assert r.status_code == 403
