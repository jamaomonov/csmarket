"""The deposit webhook: a signature or 403; the body is never trusted — a check is queued."""

# ruff: noqa: F811  -- the imported ``sales_on`` fixture is requested by parameter name

from __future__ import annotations

import base64
import hashlib
from decimal import Decimal

import pytest
from csmarket.core.config import get_settings
from csmarket.core.ids import new_id
from csmarket.modules.sales.checks import drain_sale_checks
from csmarket.modules.sales.models import Sale, SaleCheck
from csmarket.modules.wallet.api import user_balance
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from structlog.testing import capture_logs

from tests.integration.fake_deposit_client import FakeDepositClient, deposit
from tests.integration.sales_factory import make_sale
from tests.integration.sales_kit import SECRET, sales_on  # noqa: F401 -- the fixture

pytestmark = pytest.mark.asyncio

URL = "/api/v1/skinslink/webhook"
TRADE = 178
#: The seller's Steam id rides the webhook; made up here, never logged.
STEAM_ID = "76561190000000001"


def _sign(trade_id: int) -> str:
    return base64.b64encode(hashlib.sha256((str(trade_id) + SECRET).encode()).digest()).decode()


def _body(sale_id: str, **over: object) -> dict[str, object]:
    body: dict[str, object] = {
        "sign": _sign(TRADE),
        "status": "hold",
        "trade_id": TRADE,
        "merchant_tx_id": sale_id,
        "steam_id": STEAM_ID,
        "amount": 12.95,
        "amount_currency": "usd",
    }
    body.update(over)
    return body


async def _checks(db: AsyncSession) -> list[str]:
    return [str(x) for x in (await db.scalars(select(SaleCheck.sale_id))).all()]


async def test_off_is_404(integration_client: AsyncClient) -> None:
    r = await integration_client.post(URL, json=_body(new_id()))
    assert r.status_code == 404


async def test_a_signed_deposit_webhook_queues_a_check_of_its_sale(
    db_session: AsyncSession, integration_client: AsyncClient, sales_on: None
) -> None:
    sale = await make_sale(db_session, status="offered")
    with capture_logs() as logs:
        r = await integration_client.post(URL, json=_body(sale.id))
    assert (r.status_code, r.json()) == (200, {"ok": True})
    assert await _checks(db_session) == [sale.id]
    assert STEAM_ID not in repr(logs)


@pytest.mark.parametrize(
    "over",
    [
        {"sign": "nope"},
        {"sign": _sign(TRADE + 1)},  # a signature made for another deposit
        {"trade_id": str(TRADE)},
        {"trade_id": True},
        {"sign": None},
    ],
)
async def test_a_forged_deposit_webhook_is_403_and_queues_nothing(
    db_session: AsyncSession,
    integration_client: AsyncClient,
    sales_on: None,
    over: dict[str, object],
) -> None:
    sale = await make_sale(db_session, status="offered")
    body = {k: v for k, v in _body(sale.id, **over).items() if v is not None}
    r = await integration_client.post(URL, json=body)
    assert r.status_code == 403, r.text
    assert await _checks(db_session) == []


@pytest.mark.parametrize("tx", ["not-a-uuid", "00000000-0000-4000-8000-000000000000", 7])
async def test_an_unknown_sale_is_answered_and_ignored(
    db_session: AsyncSession, integration_client: AsyncClient, sales_on: None, tx: object
) -> None:
    r = await integration_client.post(URL, json=_body("x", merchant_tx_id=tx))
    assert r.status_code == 200
    assert await _checks(db_session) == []


async def test_the_webhook_body_is_never_trusted(
    db_session: AsyncSession, integration_client: AsyncClient, sales_on: None
) -> None:
    sale = await make_sale(db_session, status="offered", payout_uzs=Decimal(158_300))
    r = await integration_client.post(URL, json=_body(sale.id, status="completed", amount=9999))
    assert r.status_code == 200
    client = FakeDepositClient(status=deposit("hold"))  # what Skinslink really says
    assert await drain_sale_checks(db_session, client=client, settings=get_settings()) == 1
    assert client.status_calls == [sale.id]
    fresh = await db_session.get(Sale, sale.id, populate_existing=True)
    assert fresh is not None
    assert fresh.status == "hold"
    assert await user_balance(db_session, sale.user_id) == 0
    assert await _checks(db_session) == []  # the check was taken
