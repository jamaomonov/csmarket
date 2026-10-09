"""``/public/webhook``: save, read, delete, and the private-address guard (plan C, Task 1)."""

from __future__ import annotations

import asyncio
import socket
from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import pytest
from csmarket.core import config as cfg
from csmarket.modules.public_api.models import ApiWebhook
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.test_public_api_buy import Headers, _customer, _env, _h  # noqa: F401

URL = "/api/v1/public/webhook"
GOOD = "https://hooks.example.com/csm"


@pytest.fixture(autouse=True)
def _dns(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    answers = {"private.example.com": "10.0.0.5"}

    real = asyncio.BaseEventLoop.getaddrinfo

    async def fake(self: Any, host: str, port: int, **kw: Any) -> list[Any]:
        if not host.endswith(".example.com"):
            return await real(self, host, port, **kw)  # type: ignore[no-any-return]
        ip = answers.get(host, "93.184.216.34")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]

    monkeypatch.setattr(asyncio.BaseEventLoop, "getaddrinfo", fake)
    yield
    cfg.get_settings.cache_clear()


def _idem() -> dict[str, str]:
    return {"Idempotency-Key": f"wh-{uuid4().hex}"}


async def test_get_is_null_without_a_webhook(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    _, token = await _customer(db_session, customer_headers)
    r = await integration_client.get(URL, headers=_h(token))
    assert r.status_code == 200
    assert r.json() is None


async def test_put_stores_and_get_returns(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    user, token = await _customer(db_session, customer_headers)
    r = await integration_client.put(URL, json={"url": GOOD}, headers={**_h(token), **_idem()})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["url"] == GOOD
    assert body["last_delivery"] is None
    got = await integration_client.get(URL, headers=_h(token))
    assert got.json()["url"] == GOOD
    row = await db_session.scalar(select(ApiWebhook).where(ApiWebhook.user_id == user.id))
    assert row is not None
    # A second PUT replaces the URL.
    r2 = await integration_client.put(
        URL, json={"url": GOOD + "2"}, headers={**_h(token), **_idem()}
    )
    assert r2.json()["url"] == GOOD + "2"


async def test_put_replay_is_idempotent(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    _, token = await _customer(db_session, customer_headers)
    h = {**_h(token), **_idem()}
    a = await integration_client.put(URL, json={"url": GOOD}, headers=h)
    b = await integration_client.put(URL, json={"url": GOOD}, headers=h)
    assert a.status_code == b.status_code == 200
    assert a.json() == b.json()


async def test_put_requires_idempotency_key(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    _, token = await _customer(db_session, customer_headers)
    r = await integration_client.put(URL, json={"url": GOOD}, headers=_h(token))
    assert r.status_code == 422


async def test_private_host_is_refused(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    _, token = await _customer(db_session, customer_headers)
    r = await integration_client.put(
        URL, json={"url": "https://private.example.com/x"}, headers={**_h(token), **_idem()}
    )
    assert r.status_code == 422
    assert r.json()["code"] == "webhook_url_private"
    bad = await integration_client.put(
        URL, json={"url": "http://hooks.example.com/x"}, headers={**_h(token), **_idem()}
    )
    assert bad.status_code == 422
    assert bad.json()["code"] == "webhook_url_invalid"


async def test_delete_then_get_null(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    _, token = await _customer(db_session, customer_headers)
    await integration_client.put(URL, json={"url": GOOD}, headers={**_h(token), **_idem()})
    d = await integration_client.delete(URL, headers={**_h(token), **_idem()})
    assert d.status_code == 204
    assert (await integration_client.get(URL, headers=_h(token))).json() is None
    # Deleting again is still 204.
    again = await integration_client.delete(URL, headers={**_h(token), **_idem()})
    assert again.status_code == 204


async def test_another_users_webhook_is_invisible(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    from csmarket.modules.public_api import keys

    from tests.integration.payments_factory import make_user

    _, token = await _customer(db_session, customer_headers)
    await integration_client.put(URL, json={"url": GOOD}, headers={**_h(token), **_idem()})
    other = await make_user(db_session)
    other.usd_wallet_enabled = True
    _, other_token = await keys.issue(db_session, user=other)
    await db_session.commit()
    r = await integration_client.get(URL, headers=_h(other_token))
    assert r.json() is None


async def test_requires_a_key(integration_client: AsyncClient) -> None:
    assert (await integration_client.get(URL)).status_code == 401


async def test_reused_key_with_another_url_is_a_conflict(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    _, token = await _customer(db_session, customer_headers)
    h = {**_h(token), **_idem()}
    assert (await integration_client.put(URL, json={"url": GOOD}, headers=h)).status_code == 200
    r = await integration_client.put(URL, json={"url": GOOD + "2"}, headers=h)
    assert r.status_code == 409
    assert r.json()["code"] == "idempotency_mismatch"
    got = await integration_client.get(URL, headers=_h(token))
    assert got.json()["url"] == GOOD


async def test_put_replay_after_delete_answers_the_original(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    _, token = await _customer(db_session, customer_headers)
    h = {**_h(token), **_idem()}
    first = await integration_client.put(URL, json={"url": GOOD}, headers=h)
    await integration_client.delete(URL, headers={**_h(token), **_idem()})
    again = await integration_client.put(URL, json={"url": GOOD}, headers=h)
    assert again.status_code == 200
    assert again.json() == first.json()
    assert (await integration_client.get(URL, headers=_h(token))).json() is None


async def test_odd_hosts_are_422_not_500(
    integration_client: AsyncClient, customer_headers: Headers, db_session: AsyncSession
) -> None:
    _, token = await _customer(db_session, customer_headers)
    for bad in ("https://a..b/x", "https://" + "a" * 64 + ".com/x"):
        r = await integration_client.put(URL, json={"url": bad}, headers={**_h(token), **_idem()})
        assert r.status_code == 422, r.text
        assert r.json()["code"] == "webhook_url_invalid"
