"""The skin-sales P&L on the dashboard and the Skinslink reconciliation (spec 2026-10-13)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from csmarket.core import clock as core_clock
from csmarket.core.ids import new_id
from csmarket.modules.fx.api import FxSnapshot
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.sales_factory import make_request, make_sale

pytestmark = pytest.mark.asyncio

Headers = Callable[[], Awaitable[dict[str, str]]]
#: 2026-10-13 12:00 in Tashkent (UTC+5).
NOW = datetime(2026, 10, 13, 7, 0, tzinfo=UTC)
CBU = Decimal(12_500)
D = Decimal


@pytest.fixture
async def headers(admin_headers: Headers) -> AsyncIterator[dict[str, str]]:
    """An admin's headers minted on the real clock, then the clock pinned to :data:`NOW`."""
    minted = await admin_headers()
    core_clock.set_clock(lambda: NOW)
    yield minted
    core_clock.reset_clock()


async def _cbu(
    db: AsyncSession, rate: Decimal = CBU, at: datetime = NOW - timedelta(days=40)
) -> None:
    db.add(FxSnapshot(id=new_id(), usd_uzs=rate, source="cbu", fetched_at=at))
    await db.commit()


async def _balance_sale(db: AsyncSession, done: datetime, **over: Any) -> Any:
    values: dict[str, Any] = {
        "status": "credited",
        "credited_at": done,
        "created_at": done - timedelta(days=8),
        "amount_usd": D("12.95"),
        "payout_uzs": D(125_000),
    }
    values.update(over)
    return await make_sale(db, **values)


async def _card_sale(db: AsyncSession, done: datetime, status: str, **over: Any) -> Any:
    sale = await make_sale(
        db,
        status="payout",
        payout_to="card",
        payout_uzs=D(150_000),
        amount_usd=D("12.95"),
        created_at=done - timedelta(days=8),
        **over,
    )
    await make_request(db, sale, status=status, to_pay_at=done, bank_fee_uzs=None)
    return sale


async def _dashboard(c: AsyncClient, headers: dict[str, str], days: int) -> Any:
    r = await c.get(f"/api/v1/admin/dashboard?days={days}", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["sales_pnl"]


async def test_the_dashboard_sums_balance_and_card_payouts(
    integration_client: AsyncClient, db_session: AsyncSession, headers: dict[str, str]
) -> None:
    await _cbu(db_session)
    await _balance_sale(db_session, NOW - timedelta(hours=1))
    await _card_sale(db_session, NOW - timedelta(hours=2), "paid")
    p = await _dashboard(integration_client, headers, 1)
    assert p["count"] == 2
    assert D(p["income_usd"]) == D("25.9")
    assert D(p["to_balances_uzs"]) == D(125_000)
    # 150 000 sent + the bank's 1 % (the default setting: the row predates the column).
    assert D(p["to_cards_uzs"]) == D(151_500)
    assert (D(p["withheld_uzs"]), D(p["bank_uzs"])) == (D(5_200), D(1_500))
    assert D(p["cost_uzs"]) == D(276_500)
    assert D(p["cost_usd"]) == D("22.12")  # at the CBU 12 500
    assert D(p["profit_usd"]) == D("3.78")
    assert p["profit_percent"] == "14.6"


async def test_a_waiting_card_is_to_pay_and_a_rejected_one_went_to_the_balance(
    integration_client: AsyncClient, db_session: AsyncSession, headers: dict[str, str]
) -> None:
    await _cbu(db_session)
    await _card_sale(db_session, NOW - timedelta(hours=1), "to_pay")
    await _card_sale(db_session, NOW - timedelta(hours=1), "rejected")
    p = await _dashboard(integration_client, headers, 1)
    assert D(p["to_pay_uzs"]) == D(151_500)
    assert D(p["to_balances_uzs"]) == D(155_200)  # items_uzs of the factory sale
    assert D(p["to_cards_uzs"]) == D(0)


async def test_a_late_evening_sale_counts_on_its_tashkent_day(
    integration_client: AsyncClient, db_session: AsyncSession, headers: dict[str, str]
) -> None:
    await _cbu(db_session)
    # 2026-10-12 23:30 Tashkent = 18:30 UTC.
    await _balance_sale(db_session, datetime(2026, 10, 12, 18, 30, tzinfo=UTC))
    assert (await _dashboard(integration_client, headers, 1))["count"] == 0
    week = await _dashboard(integration_client, headers, 7)
    days = {d["day"]: d["count"] for d in week["by_day"]}
    assert days["2026-10-12"] == 1
    assert len(week["by_day"]) == 7


async def test_open_sales_and_newer_rates_are_left_out(
    integration_client: AsyncClient, db_session: AsyncSession, headers: dict[str, str]
) -> None:
    await _cbu(db_session)
    await _cbu(db_session, rate=D(20_000), at=NOW - timedelta(minutes=5))  # after the sale
    await make_sale(db_session, status="hold")
    await _balance_sale(db_session, NOW - timedelta(hours=1))
    p = await _dashboard(integration_client, headers, 1)
    assert p["count"] == 1
    assert D(p["cost_usd"]) == D(10)  # 125 000 at 12 500, not at 20 000


async def test_an_empty_window_is_zeros(
    integration_client: AsyncClient, headers: dict[str, str]
) -> None:
    p = await _dashboard(integration_client, headers, 30)
    assert (p["count"], p["income_usd"], p["profit_percent"]) == (0, "0", "0")
    assert len(p["by_day"]) == 30


async def _recon(c: AsyncClient, headers: dict[str, str], query: str = "") -> Any:
    r = await c.get(f"/api/v1/admin/sales/reconciliation?days=7{query}", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


async def test_reconciliation_flags_and_totals(
    integration_client: AsyncClient, db_session: AsyncSession, headers: dict[str, str]
) -> None:
    hour = timedelta(hours=1)
    clean = await _balance_sale(db_session, NOW - hour)
    short = await _balance_sale(db_session, NOW - 2 * hour, amount_usd=D("12.00"))
    missing = await _balance_sale(db_session, NOW - 3 * hour, amount_usd=None)
    reverted = await _balance_sale(
        db_session, NOW - timedelta(days=20), attention_reason="rolled_back"
    )
    body = await _recon(integration_client, headers)
    flags = {i["number"]: i["flag"] for i in body["items"]}
    assert flags == {
        clean.number: None,
        short.number: "short",
        missing.number: "missing",
        reverted.number: "reverted",  # open, so listed whatever its date
    }
    assert body["problems"] == 3
    assert D(body["expected_usd"]) == D("12.95") * 4
    assert D(body["credited_usd"]) == D("12.95") * 2 + D(12)
    row = next(i for i in body["items"] if i["number"] == short.number)
    assert (row["quoted_usd"], row["amount_usd"], row["diff_usd"]) == ("12.95", "12", "-0.95")
    only = await _recon(integration_client, headers, "&problems=true")
    assert {i["number"] for i in only["items"]} == {short.number, missing.number, reverted.number}
    assert only["problems"] == 3


async def test_reconciliation_pages_by_cursor(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import csmarket.modules.sales.pnl_query as q

    real = q.reconciliation

    async def small(*args: Any, **kw: Any) -> Any:
        return await real(*args, **{**kw, "limit": 2})

    monkeypatch.setattr("csmarket.modules.sales.admin_recon_routes.reconciliation", small)
    made = [await _balance_sale(db_session, NOW - timedelta(hours=n)) for n in (1, 2, 3)]
    first = await _recon(integration_client, headers)
    assert [i["number"] for i in first["items"]] == [made[0].number, made[1].number]
    second = await _recon(integration_client, headers, f"&cursor={first['next_cursor']}")
    assert [i["number"] for i in second["items"]] == [made[2].number]
    assert second["next_cursor"] is None


async def test_reconciliation_refuses_other_windows_and_customers(
    integration_client: AsyncClient,
    headers: dict[str, str],
    customer_headers: Headers,
) -> None:
    bad = await integration_client.get("/api/v1/admin/sales/reconciliation?days=3", headers=headers)
    assert (bad.status_code, bad.json()["code"]) == (422, "dashboard_days")
    # Minted on the real clock: a token issued at the pinned NOW reads as expired (401).
    core_clock.reset_clock()
    customer = await customer_headers()
    r = await integration_client.get("/api/v1/admin/sales/reconciliation", headers=customer)
    assert r.status_code == 403
