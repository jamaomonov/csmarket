"""Final-review fixes for «Мои сделки»: an adopted deposit without an amount, a revert in
hold, resolving without a price, repricing after a resolution."""

# ruff: noqa: F811  -- imported fixtures are requested by parameter name

from __future__ import annotations

from collections.abc import Iterator

import pytest
from csmarket.modules.desk import deposits as desk_deposits
from csmarket.modules.desk.models import DeskDeposit
from csmarket.modules.skinslink.api import SkinslinkUnavailableError
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.desk_factory import BASE, Headers, create, desk_headers, key  # noqa: F401
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


async def test_an_adopted_deposit_without_an_amount_is_credited_at_the_quote(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    desk_headers: Headers,
    fake: FakeDepositClient,
) -> None:
    """``deposit/status`` carries no USD amount: the items' Skinslink prices stand in."""
    h = await desk_headers()
    deal = await create(integration_client, h, **PRICED)
    fake.created = SkinslinkUnavailableError("timeout")
    await integration_client.post(f"{BASE}/deals/{deal['id']}/deposit", headers=h | key())
    fake.status = deposit("completed", amount_usd=None)
    await desk_deposits.check_deposit(db_session, fake, deposit_id=(await _row(db_session)).id)
    page = (await integration_client.get(f"{BASE}/deals/{deal['id']}", headers=h)).json()
    assert (page["status"], page["profit_usd"]) == ("closed", "100")
    assert page["deposits"][0]["amount_usd"] == "1200"
    assert page["deposits"][0]["amount_estimated"] is True


async def test_a_revert_in_hold_is_a_loss_of_the_cost(
    integration_client: AsyncClient,
    db_session: AsyncSession,
    desk_headers: Headers,
    fake: FakeDepositClient,
) -> None:
    h = await desk_headers()
    deal = await create(integration_client, h, **PRICED)
    fake.created = deposit("hold")
    await integration_client.post(f"{BASE}/deals/{deal['id']}/deposit", headers=h | key())
    fake.status = deposit("reverted")
    await desk_deposits.check_deposit(db_session, fake, deposit_id=(await _row(db_session)).id)
    page = (await integration_client.get(f"{BASE}/deals/{deal['id']}", headers=h)).json()
    assert (page["status"], page["profit_usd"]) == ("reverted", "-1100")
    summary = (await integration_client.get(f"{BASE}/summary", headers=h)).json()
    assert (summary["profit_usd"], summary["skinslink_share_usd"]) == ("-1100", "0")


@pytest.mark.parametrize("action", ["deposit", "sell", "write-off"])
async def test_nothing_resolves_before_the_deal_has_a_price(
    integration_client: AsyncClient,
    desk_headers: Headers,
    fake: FakeDepositClient,
    action: str,
) -> None:
    h = await desk_headers()
    deal = await create(
        integration_client,
        h,
        items=[
            {
                "name": "A",
                "asset_id": "1",
                "skinslink_usd": "10",
                "destination": "stock" if action != "deposit" else "skinslink",
            }
        ],
    )
    item = deal["items"][0]["id"]
    url, body = {
        "deposit": (f"{BASE}/deals/{deal['id']}/deposit", None),
        "sell": (f"{BASE}/items/{item}/sell", {"where": "x", "amount": "5", "currency": "USD"}),
        "write-off": (f"{BASE}/items/{item}/write-off", {"note": "lost"}),
    }[action]
    r = await integration_client.post(url, json=body, headers=h | key())
    assert (r.status_code, r.json()["code"]) == (409, "price_required")
    assert fake.deposit_calls == []


async def test_the_price_is_locked_once_an_item_is_resolved(
    integration_client: AsyncClient, desk_headers: Headers
) -> None:
    h = await desk_headers()
    deal = await create(
        integration_client,
        h,
        items=[
            {"name": "A", "skinslink_usd": "50", "destination": "stock"},
            {"name": "B", "skinslink_usd": "50", "destination": "stock"},
        ],
        paid_amount="1000",
        paid_currency="USD",
    )
    a = deal["items"][0]["id"]
    await integration_client.post(
        f"{BASE}/items/{a}/sell",
        json={"where": "x", "amount": "600", "currency": "USD"},
        headers=h | key(),
    )
    r = await integration_client.patch(
        f"{BASE}/deals/{deal['id']}",
        json={"paid_amount": "1200", "paid_currency": "USD"},
        headers=h | key(),
    )
    assert (r.status_code, r.json()["code"]) == (409, "price_locked")
    note = await integration_client.patch(
        f"{BASE}/deals/{deal['id']}", json={"note": "ok"}, headers=h | key()
    )
    assert note.status_code == 200
