"""«Мои сделки»: a deal's skins sent to Skinslink and the deposit followed (spec
2026-10-29-desk «Selling to Skinslink», plan Review Focus 1–3)."""

# ruff: noqa: F811  -- imported fixtures are requested by parameter name

from __future__ import annotations

import base64
import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from csmarket.modules.desk import deposits as desk_deposits
from csmarket.modules.desk.models import DeskDeposit
from csmarket.modules.desk.poll import poll_deposits
from csmarket.modules.sales.models import SaleCheck
from csmarket.modules.skinslink.api import SkinslinkError, SkinslinkUnavailableError
from fastapi import FastAPI
from httpx import AsyncClient, Response
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.integration.desk_factory import BASE, Headers, create, desk_headers, key  # noqa: F401
from tests.integration.fake_deposit_client import FakeDepositClient, deposit
from tests.integration.sales_kit import SECRET, sales_on, use_client  # noqa: F401

pytestmark = pytest.mark.asyncio

PRICED = {"paid_amount": "1100", "paid_currency": "USD"}


@pytest.fixture
def fake(integration_app: FastAPI) -> Iterator[FakeDepositClient]:
    client = FakeDepositClient(created=deposit("active"), status=deposit("active"))
    use_client(integration_app, client)
    yield client
    integration_app.dependency_overrides.clear()


async def _send(c: AsyncClient, h: dict[str, str], deal_id: str) -> Response:
    return await c.post(f"{BASE}/deals/{deal_id}/deposit", headers=h | key())


async def _deposit_row(db: AsyncSession) -> DeskDeposit:
    db.expire_all()
    row = await db.scalar(select(DeskDeposit))
    assert row is not None
    return row


async def _get(c: AsyncClient, h: dict[str, str], deal_id: str) -> dict[str, Any]:
    out: dict[str, Any] = (await c.get(f"{BASE}/deals/{deal_id}", headers=h)).json()
    return out


async def test_send_commits_creating_then_calls_once(
    integration_client: AsyncClient, desk_headers: Headers, fake: FakeDepositClient
) -> None:
    h = await desk_headers()
    deal = await create(integration_client, h, **PRICED)
    r = await _send(integration_client, h, deal["id"])
    assert r.status_code == 200, r.text
    [call] = fake.deposit_calls
    assert str(call["merchant_tx_id"]).startswith("desk-")
    assert call["asset_ids"] == ["100", "101"]
    assert call["min_prices"] == {"100": Decimal("792"), "101": Decimal("396")}
    body = r.json()
    assert [i["state"] for i in body["items"]] == ["sent", "sent"]
    assert body["deposits"][0]["status"] == "active"


async def test_timeout_leaves_creating_and_poll_adopts_it(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    db_engine: AsyncEngine,
    desk_headers: Headers,
    fake: FakeDepositClient,
) -> None:
    h = await desk_headers()
    deal = await create(integration_client, h, **PRICED)
    fake.created = SkinslinkUnavailableError("timeout")
    r = await _send(integration_client, h, deal["id"])
    assert r.status_code == 200
    assert (await _deposit_row(db_session)).status == "creating"
    again = await _send(integration_client, h, deal["id"])
    assert (again.status_code, again.json()["code"]) == (409, "deposit_open")
    await db_session.execute(update(DeskDeposit).values(next_check_at=datetime.now(UTC)))
    await db_session.commit()
    fake.status = deposit("hold", amount_usd=Decimal("1200"))
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    assert await poll_deposits(factory, fake) == 1
    assert len(fake.deposit_calls) == 1  # never sent twice
    page = await _get(integration_client, h, deal["id"])
    assert page["status"] == "received"
    assert page["protected_until"] is not None


async def test_prices_moved_frees_the_items(
    integration_client: AsyncClient, desk_headers: Headers, fake: FakeDepositClient
) -> None:
    h = await desk_headers()
    deal = await create(integration_client, h, **PRICED)
    fake.created = SkinslinkError("x", code="inventory_reload", status=400)
    r = await _send(integration_client, h, deal["id"])
    assert (r.status_code, r.json()["code"]) == (409, "prices_moved")
    page = await _get(integration_client, h, deal["id"])
    assert [i["state"] for i in page["items"]] == ["open", "open"]
    retry = await _send(integration_client, h, deal["id"])  # the failed one is not open
    assert retry.status_code == 409


async def test_nothing_to_send_and_no_link(
    integration_client: AsyncClient, desk_headers: Headers, fake: FakeDepositClient
) -> None:
    h = await desk_headers()
    stock_only = await create(
        integration_client, h, items=[{"name": "x", "asset_id": "9", "destination": "stock"}]
    )
    r = await _send(integration_client, h, stock_only["id"])
    assert r.json()["code"] == "nothing_to_send"
    no_link = await create(integration_client, h, trade_link=None)
    r2 = await _send(integration_client, h, no_link["id"])
    assert r2.json()["code"] == "trade_link_missing"


async def _credited_deal(
    c: AsyncClient, db: AsyncSession, h: dict[str, str], fake: FakeDepositClient
) -> tuple[str, DeskDeposit]:
    deal = await create(c, h, **PRICED)
    fake.created = deposit("completed", amount_usd=Decimal("1200"))
    await _send(c, h, deal["id"])
    return str(deal["id"]), await _deposit_row(db)


async def test_credit_splits_revenue_and_closes_the_deal(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    desk_headers: Headers,
    fake: FakeDepositClient,
) -> None:
    h = await desk_headers()
    deal_id, _ = await _credited_deal(integration_client, db_session, h, fake)
    page = await _get(integration_client, h, deal_id)
    assert (page["status"], page["profit_usd"], page["resolved"]) == ("closed", "100", True)
    s = (await integration_client.get(f"{BASE}/summary", headers=h)).json()
    assert (s["profit_usd"], s["revenue_usd"], s["skinslink_share_usd"]) == ("100", "1200", "1200")


async def test_revert_after_credit_is_a_loss_on_the_revert_day(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    desk_headers: Headers,
    fake: FakeDepositClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = await desk_headers()
    deal_id, dep = await _credited_deal(integration_client, db_session, h, fake)
    later = datetime.now(UTC) + timedelta(days=3)
    monkeypatch.setattr(desk_deposits, "now", lambda: later)
    fake.status = deposit("reverted", amount_usd=Decimal("1200"))
    await desk_deposits.check_deposit(db_session, fake, deposit_id=dep.id)
    page = await _get(integration_client, h, deal_id)
    assert (page["status"], page["profit_usd"]) == ("reverted", "-1100")
    today = datetime.now(UTC).date().isoformat()
    first = (
        await integration_client.get(
            f"{BASE}/summary", params={"from": today, "to": today}, headers=h
        )
    ).json()
    assert first["profit_usd"] == "100"  # the credit day is not rewritten
    whole = (
        await integration_client.get(
            f"{BASE}/summary", params={"to": later.date().isoformat()}, headers=h
        )
    ).json()
    assert (whole["profit_usd"], whole["skinslink_share_usd"]) == ("-1100", "0")


def _sign(trade_id: int) -> str:
    return base64.b64encode(hashlib.sha256((str(trade_id) + SECRET).encode()).digest()).decode()


async def test_webhook_routes_desk_ids_to_the_desk(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    desk_headers: Headers,
    fake: FakeDepositClient,
    sales_on: None,
) -> None:
    h = await desk_headers()
    deal = await create(integration_client, h, **PRICED)
    await _send(integration_client, h, deal["id"])
    dep = await _deposit_row(db_session)
    before = dep.next_check_at
    r = await integration_client.post(
        "/api/v1/skinslink/webhook",
        json={
            "sign": _sign(178),
            "status": "hold",
            "trade_id": 178,
            "merchant_tx_id": f"desk-{dep.id}",
        },
    )
    assert r.status_code == 200, r.text
    assert (await _deposit_row(db_session)).next_check_at <= before
    assert (await db_session.scalars(select(SaleCheck))).all() == []


async def test_webhook_sale_id_never_touches_desk(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    desk_headers: Headers,
    fake: FakeDepositClient,
    sales_on: None,
) -> None:
    h = await desk_headers()
    deal = await create(integration_client, h, **PRICED)
    await _send(integration_client, h, deal["id"])
    dep = await _deposit_row(db_session)
    before = dep.next_check_at
    r = await integration_client.post(
        "/api/v1/skinslink/webhook",
        json={"sign": _sign(179), "status": "hold", "trade_id": 179, "merchant_tx_id": dep.id},
    )
    assert r.status_code == 200
    assert (await _deposit_row(db_session)).next_check_at == before


async def test_poll_tick_survives_one_failure(  # noqa: PLR0917 -- fixtures
    integration_client: AsyncClient,
    db_session: AsyncSession,
    db_engine: AsyncEngine,
    desk_headers: Headers,
    fake: FakeDepositClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = await desk_headers()
    for _ in range(2):
        deal = await create(integration_client, h, **PRICED)
        await _send(integration_client, h, deal["id"])
    await db_session.execute(update(DeskDeposit).values(next_check_at=datetime.now(UTC)))
    await db_session.commit()
    calls = {"n": 0}
    real = desk_deposits.check_deposit

    async def _flaky(db: AsyncSession, client: object, *, deposit_id: str) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        await real(db, client, deposit_id=deposit_id)  # type: ignore[arg-type]

    monkeypatch.setattr("csmarket.modules.desk.poll.check_deposit", _flaky)
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    assert await poll_deposits(factory, fake) == 2
    assert calls["n"] == 2
