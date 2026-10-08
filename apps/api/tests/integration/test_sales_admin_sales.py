# apps/api/tests/integration/test_sales_admin_sales.py
"""«Продажи» and «Настройки выкупа»: the list, a sale's page, the audited settings save."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from decimal import Decimal

import pytest
from csmarket.modules.admin.models import AdminAuditLog
from csmarket.modules.sales.rules import DEFAULT_SALE_SETTINGS
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.sales_factory import make_sale
from tests.integration.sales_kit import add_rate

pytestmark = pytest.mark.asyncio

Headers = Callable[[], Awaitable[dict[str, str]]]
BASE = "/api/v1/admin/sales"
KEY = {"Idempotency-Key": "test-admin-sale-settings-01"}


async def test_the_list_filters_by_status_and_number(
    db_session: AsyncSession, integration_client: AsyncClient, admin_headers: Headers
) -> None:
    headers = await admin_headers()
    hold = await make_sale(db_session, status="hold")
    await make_sale(db_session, status="credited")
    r = await integration_client.get(BASE, params={"status": "hold"}, headers=headers)
    assert [s["number"] for s in r.json()["items"]] == [hold.number]
    r = await integration_client.get(BASE, params={"q": hold.number[:5].lower()}, headers=headers)
    assert [s["number"] for s in r.json()["items"]] == [hold.number]


async def test_a_sales_page_shows_skinslinks_amount_our_payout_and_margin(
    db_session: AsyncSession, integration_client: AsyncClient, admin_headers: Headers
) -> None:
    headers = await admin_headers()
    sale = await make_sale(db_session, status="credited", amount_usd=Decimal("12.83"), trade_id=178)
    body = (await integration_client.get(f"{BASE}/{sale.number}", headers=headers)).json()
    assert (body["quoted_usd"], body["amount_usd"], body["margin_usd"], body["trade_id"]) == (
        "12.95",
        "12.83",
        "0.6735",
        178,
    )
    assert (await integration_client.get(f"{BASE}/S0000000", headers=headers)).status_code == 404


async def test_the_settings_save_is_audited_and_replayed(
    db_session: AsyncSession, integration_client: AsyncClient, admin_headers: Headers
) -> None:
    headers = await admin_headers()
    await add_rate(db_session)
    view = (await integration_client.get(f"{BASE}/settings", headers=headers)).json()
    assert view["settings"]["enabled"] is False
    assert view["rate_uzs"] == "12650.5"
    doc = {**DEFAULT_SALE_SETTINGS.model_dump(mode="json"), "enabled": True, "card_min_uzs": 50_000}
    first = await integration_client.put(f"{BASE}/settings", json=doc, headers={**headers, **KEY})
    again = await integration_client.put(f"{BASE}/settings", json=doc, headers={**headers, **KEY})
    assert first.status_code == again.status_code == 200
    assert first.json()["settings"]["card_min_uzs"] == 50_000
    assert first.json()["updated_by"] is not None
    actions = (await db_session.scalars(select(AdminAuditLog.action))).all()
    assert list(actions) == ["sales.settings.save"]


async def test_the_settings_audit_records_each_changed_field(
    db_session: AsyncSession, integration_client: AsyncClient, admin_headers: Headers
) -> None:
    headers = await admin_headers()
    base = DEFAULT_SALE_SETTINGS.model_dump(mode="json")
    doc = {**base, "balance_bonus_pct": "3.00", "card_min_uzs": 55_000}
    r = await integration_client.put(f"{BASE}/settings", json=doc, headers={**headers, **KEY})
    assert r.status_code == 200
    payload: dict[str, str] = (await db_session.scalars(select(AdminAuditLog.payload))).one()
    assert set(payload) == {"balance_bonus_pct", "card_min_uzs"}
    assert payload["balance_bonus_pct"].endswith('-> "3.00"')
    assert payload["card_min_uzs"].endswith("-> 55000")


async def test_a_bad_settings_document_is_422(
    integration_client: AsyncClient, admin_headers: Headers
) -> None:
    headers = await admin_headers()
    doc = {
        **DEFAULT_SALE_SETTINGS.model_dump(mode="json"),
        "margin": [{"from_usd": "1", "percent": "5"}],
    }
    r = await integration_client.put(f"{BASE}/settings", json=doc, headers={**headers, **KEY})
    assert r.status_code == 422


async def test_the_sales_list_pages_by_cursor(
    db_session: AsyncSession, integration_client: AsyncClient, admin_headers: Headers
) -> None:
    headers = await admin_headers()
    made = {(await make_sale(db_session, status="hold")).number for _ in range(3)}
    first = (await integration_client.get(BASE, params={"limit": 2}, headers=headers)).json()
    assert len(first["items"]) == 2
    assert first["next_cursor"] is not None
    second = (
        await integration_client.get(
            BASE, params={"limit": 2, "cursor": first["next_cursor"]}, headers=headers
        )
    ).json()
    assert len(second["items"]) == 1
    assert second["next_cursor"] is None
    assert {s["number"] for s in first["items"] + second["items"]} == made
