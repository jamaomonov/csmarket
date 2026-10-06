"""The Skinslink webhook: a signature or 403; the body is never trusted — a check is queued."""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Iterator
from typing import Any

import pytest
from csmarket.core import config as cfg
from csmarket.modules.skinslink.models import SkinslinkCheck
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.skinslink_factory import PURCHASE_ID, make_skinslink_order

pytestmark = pytest.mark.asyncio

URL = "/api/v1/skinslink/webhook"
SECRET = "test-secret-not-real"


def _sign(id_: int) -> str:
    return base64.b64encode(hashlib.sha256((str(id_) + SECRET).encode()).digest()).decode()


@pytest.fixture
def active(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for name, value in {
        "SKINSLINK_ENABLED": "true",
        "SKINSLINK_API_KEY": "k",
        "SKINSLINK_SECRET": SECRET,
    }.items():
        monkeypatch.setenv(f"CSMARKET_{name}", value)
    cfg.get_settings.cache_clear()
    yield
    cfg.get_settings.cache_clear()


async def _checks(db: AsyncSession) -> list[int]:
    return list((await db.scalars(select(SkinslinkCheck.purchase_id))).all())


async def test_disabled_is_404(integration_client: AsyncClient) -> None:
    r = await integration_client.post(URL, json={"purchase_id": 1, "sign": _sign(1)})
    assert r.status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {"purchase_id": PURCHASE_ID, "sign": "nope", "status": "completed"},
        {"purchase_id": PURCHASE_ID, "status": "completed"},
        {"purchase_id": str(PURCHASE_ID), "sign": _sign(PURCHASE_ID)},
        {"purchase_id": True, "sign": _sign(1)},
        {"sign": _sign(PURCHASE_ID)},
    ],
)
async def test_a_bad_signature_is_403_and_queues_nothing(
    integration_client: AsyncClient, db_session: AsyncSession, active: None, body: dict[str, Any]
) -> None:
    r = await integration_client.post(URL, json=body)
    assert r.status_code == 403, r.text
    assert await _checks(db_session) == []


async def test_a_body_that_is_not_json_is_400(
    integration_client: AsyncClient, active: None
) -> None:
    r = await integration_client.post(
        URL, content=b"purchase_id=1", headers={"content-type": "application/json"}
    )
    assert r.status_code == 400


async def test_a_good_signature_queues_a_check_and_answers_200(
    integration_client: AsyncClient, db_session: AsyncSession, active: None
) -> None:
    body = {"purchase_id": PURCHASE_ID, "sign": _sign(PURCHASE_ID), "status": "completed"}
    r = await integration_client.post(URL, json=body)
    assert (r.status_code, r.json()) == (200, {"ok": True})
    assert await _checks(db_session) == [PURCHASE_ID]


async def test_the_body_is_not_trusted(
    integration_client: AsyncClient, db_session: AsyncSession, active: None
) -> None:
    order, _ = await make_skinslink_order(db_session)
    body = {"purchase_id": PURCHASE_ID, "sign": _sign(PURCHASE_ID), "status": "completed"}
    assert (await integration_client.post(URL, json=body)).status_code == 200
    await db_session.refresh(order)
    assert order.status == "trade_sent"  # only the check (which asks Skinslink) moves it


async def test_a_deposit_webhook_is_accepted_and_ignored(
    integration_client: AsyncClient, db_session: AsyncSession, active: None
) -> None:
    r = await integration_client.post(URL, json={"trade_id": 5, "sign": _sign(5)})
    assert r.status_code == 200
    assert await _checks(db_session) == []


async def test_duplicates_are_harmless(
    integration_client: AsyncClient, db_session: AsyncSession, active: None
) -> None:
    for _ in range(2):
        await integration_client.post(URL, json={"purchase_id": 9, "sign": _sign(9)})
    count = await db_session.scalar(select(func.count()).select_from(SkinslinkCheck))
    assert count == 2  # two one-shot checks; asking Skinslink twice is idempotent


async def test_the_webhook_is_not_rate_limited_by_the_coarse_tier(
    integration_client: AsyncClient, active: None
) -> None:
    for _ in range(70):
        r = await integration_client.post(URL, json={"trade_id": 5, "sign": _sign(5)})
        assert r.status_code == 200
