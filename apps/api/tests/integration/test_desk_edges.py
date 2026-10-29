"""«Мои сделки»: the less travelled paths — 404, paging, the rate, Skinslink refusing or
down, a lost deposit, a status read that fails."""

# ruff: noqa: F811  -- imported fixtures are requested by parameter name

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from csmarket.modules.desk import deals as desk_deals
from csmarket.modules.desk import deposits as desk_deposits
from csmarket.modules.desk.models import DeskDeposit
from csmarket.modules.fx.api import record_snapshot
from csmarket.modules.skinslink.api import (
    SkinslinkError,
    SkinslinkForbiddenError,
    SkinslinkUnavailableError,
)
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.desk_factory import (  # noqa: F401
    BASE,
    LINK,
    Headers,
    create,
    desk_headers,
    key,
)
from tests.integration.fake_deposit_client import FakeDepositClient, deposit
from tests.integration.sales_kit import use_client

pytestmark = pytest.mark.asyncio
PRICED = {"paid_amount": "1100", "paid_currency": "USD"}


@pytest.fixture
def fake(integration_app: FastAPI) -> Iterator[FakeDepositClient]:
    client = FakeDepositClient(created=deposit("active"), status=deposit("active"))
    use_client(integration_app, client)
    yield client
    integration_app.dependency_overrides.clear()


async def _row(db: AsyncSession) -> DeskDeposit:
    db.expire_all()
    row = await db.scalar(select(DeskDeposit))
    assert row is not None
    return row


async def test_unknown_deal_is_404(integration_client: AsyncClient, desk_headers: Headers) -> None:
    r = await integration_client.get(
        f"{BASE}/deals/{'0' * 8}-0000-7000-8000-{'0' * 12}", headers=await desk_headers()
    )
    assert (r.status_code, r.json()["code"]) == (404, "deal_not_found")


async def test_paging_status_filter_and_a_bad_cursor(
    integration_client: AsyncClient, desk_headers: Headers, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(desk_deals, "PAGE", 2)
    h = await desk_headers()
    ids = [(await create(integration_client, h))["id"] for _ in range(3)]
    first = (await integration_client.get(f"{BASE}/deals", headers=h)).json()
    assert first["next_cursor"] is not None
    second = (
        await integration_client.get(
            f"{BASE}/deals", params={"cursor": first["next_cursor"]}, headers=h
        )
    ).json()
    seen = [d["id"] for d in first["items"] + second["items"]]
    assert sorted(seen) == sorted(ids)
    assert second["next_cursor"] is None
    paid = (
        await integration_client.get(f"{BASE}/deals", params={"status": "paid"}, headers=h)
    ).json()
    assert paid["items"] == []
    bad = await integration_client.get(f"{BASE}/deals", params={"cursor": "%%%"}, headers=h)
    assert bad.status_code == 422


async def test_the_rate_is_the_cbu_one(
    integration_client: AsyncClient, db_session: AsyncSession, desk_headers: Headers
) -> None:
    h = await desk_headers()
    assert (await integration_client.get(f"{BASE}/rate", headers=h)).json() == {"usd_uzs": None}
    await record_snapshot(db_session, rate=Decimal("12650.5"), source="cbu")
    await db_session.commit()
    assert (await integration_client.get(f"{BASE}/rate", headers=h)).json() == {
        "usd_uzs": "12650.5"
    }


async def test_patch_link_rate_and_date(
    integration_client: AsyncClient, desk_headers: Headers
) -> None:
    h = await desk_headers()
    deal = await create(integration_client, h, trade_link=None)
    r = await integration_client.patch(
        f"{BASE}/deals/{deal['id']}",
        json={
            "trade_link": LINK,
            "paid_amount": "13000000",
            "paid_currency": "UZS",
            "rate": "13000",
            "paid_at": "2026-10-20T10:00:00Z",
            "note": None,
        },
        headers=h | key(),
    )
    body = r.json()
    assert (body["trade_link"], body["paid_usd"], body["note"]) == (LINK, "1000", None)
    assert body["paid_at"].startswith("2026-10-20")
    rate_only = await integration_client.patch(
        f"{BASE}/deals/{deal['id']}", json={"rate": "12500"}, headers=h | key()
    )
    assert rate_only.json()["paid_usd"] == "1040"


async def test_inventory_down_is_503(
    integration_client: AsyncClient, desk_headers: Headers, fake: FakeDepositClient
) -> None:
    fake.inventories.append(SkinslinkUnavailableError("down"))
    r = await integration_client.post(
        f"{BASE}/inventory", json={"trade_link": LINK}, headers=await desk_headers()
    )
    assert (r.status_code, r.json()["code"]) == (503, "desk_unavailable")
    fake.inventories.clear()
    fake.inventories.append(SkinslinkError("x", code="weird", status=400))
    r2 = await integration_client.post(
        f"{BASE}/inventory", json={"trade_link": LINK}, headers=await desk_headers()
    )
    assert r2.status_code == 503


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (SkinslinkForbiddenError("ip", status=403), 503, "desk_unavailable"),
        (SkinslinkError("x", code="profile_private", status=400), 409, "steam_refused"),
    ],
)
async def test_a_refused_offer_frees_the_items(  # noqa: PLR0917 -- fixtures + parameters
    integration_client: AsyncClient,
    desk_headers: Headers,
    fake: FakeDepositClient,
    error: Exception,
    status: int,
    code: str,
) -> None:
    h = await desk_headers()
    deal = await create(integration_client, h, **PRICED)
    fake.created = error
    r = await integration_client.post(f"{BASE}/deals/{deal['id']}/deposit", headers=h | key())
    assert (r.status_code, r.json()["code"]) == (status, code)
    page = (await integration_client.get(f"{BASE}/deals/{deal['id']}", headers=h)).json()
    assert [i["state"] for i in page["items"]] == ["open", "open"]


async def test_already_exists_is_adopted(
    integration_client: AsyncClient, desk_headers: Headers, fake: FakeDepositClient
) -> None:
    h = await desk_headers()
    deal = await create(integration_client, h, **PRICED)
    fake.created = SkinslinkError("dup", code="already_exists", status=409)
    fake.status = deposit("hold")
    r = await integration_client.post(f"{BASE}/deals/{deal['id']}/deposit", headers=h | key())
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "received"


async def test_a_lost_deposit_is_given_up_after_the_grace(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    desk_headers: Headers,
    fake: FakeDepositClient,
) -> None:
    h = await desk_headers()
    deal = await create(integration_client, h, **PRICED)
    fake.created = SkinslinkUnavailableError("timeout")
    await integration_client.post(f"{BASE}/deals/{deal['id']}/deposit", headers=h | key())
    dep = await _row(db_session)
    fake.status = None
    await desk_deposits.check_deposit(db_session, fake, deposit_id=dep.id)
    assert (await _row(db_session)).status == "creating"  # still within the grace
    old = datetime.now(UTC) - timedelta(minutes=11)
    await db_session.execute(update(DeskDeposit).values(created_at=old))
    await db_session.commit()
    await desk_deposits.check_deposit(db_session, fake, deposit_id=dep.id)
    assert (await _row(db_session)).status == "failed"
    page = (await integration_client.get(f"{BASE}/deals/{deal['id']}", headers=h)).json()
    assert [i["state"] for i in page["items"]] == ["open", "open"]


async def test_a_failed_status_read_waits_a_minute(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    desk_headers: Headers,
    fake: FakeDepositClient,
) -> None:
    h = await desk_headers()
    deal = await create(integration_client, h, **PRICED)
    await integration_client.post(f"{BASE}/deals/{deal['id']}/deposit", headers=h | key())
    dep = await _row(db_session)
    fake.status = SkinslinkUnavailableError("down")
    await desk_deposits.check_deposit(db_session, fake, deposit_id=dep.id)
    assert (await _row(db_session)).status == "active"
    fake.status = deposit("canceled")
    await desk_deposits.check_deposit(db_session, fake, deposit_id=dep.id)
    page = (await integration_client.get(f"{BASE}/deals/{deal['id']}", headers=h)).json()
    assert [i["state"] for i in page["items"]] == ["open", "open"]
    assert await desk_deposits.mark_due(db_session, 42) is False
