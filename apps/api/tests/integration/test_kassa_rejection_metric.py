"""``csmarket_kassa_rejections_total``: one increment per refused webhook, read back through
the ``/metrics`` text a Prometheus scrape sees.

The counter is process-global, so every test compares before/after. A rejection is counted
in exactly one place per kassa; a successful call, or a refusal for a business reason
(``-2`` wrong amount, ``-31050`` unknown account, ...), counts nothing. Every key here is fake.
"""

from __future__ import annotations

import base64
import hashlib
import re
from collections.abc import Iterator

import pytest
from csmarket.core.config import get_settings
from httpx import AsyncClient

CLICK_SERVICE_ID = "108149"
CLICK_SECRET = "fake-click-secret"
PAYME_KEY = "fake-payme-sandbox-key"
UZUM_SERVICE_ID = 101202
UZUM_LOGIN, UZUM_PASSWORD = "fake-uzum-sandbox", "fake-sandbox-password"

_LINE = re.compile(
    r'^csmarket_kassa_rejections_total\{provider="(\w+)",reason="(\w+)"\} ([\d.e+]+)$'
)


@pytest.fixture(autouse=True)
def _kassa_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("CSMARKET_CLICK_MERCHANT_ID", "5000")
    monkeypatch.setenv("CSMARKET_CLICK_SERVICE_ID", CLICK_SERVICE_ID)
    monkeypatch.setenv("CSMARKET_CLICK_SECRET_KEY", CLICK_SECRET)
    monkeypatch.setenv("CSMARKET_PAYME_MERCHANT_ID", "6a1faaca155c8e168e2a0000")
    monkeypatch.setenv("CSMARKET_PAYME_TEST_KEY", PAYME_KEY)
    monkeypatch.setenv("CSMARKET_UZUM_SERVICE_ID", str(UZUM_SERVICE_ID))
    monkeypatch.setenv("CSMARKET_UZUM_TEST_LOGIN", UZUM_LOGIN)
    monkeypatch.setenv("CSMARKET_UZUM_TEST_PASSWORD", UZUM_PASSWORD)
    get_settings.cache_clear()
    yield
    monkeypatch.undo()
    get_settings.cache_clear()


async def _counts(client: AsyncClient) -> dict[tuple[str, str], float]:
    text = (await client.get("/metrics")).text
    found: dict[tuple[str, str], float] = {}
    for line in text.splitlines():
        match = _LINE.match(line)
        if match:
            found[(match.group(1), match.group(2))] = float(match.group(3))
    return found


async def _delta(
    client: AsyncClient, before: dict[tuple[str, str], float]
) -> dict[tuple[str, str], float]:
    after = await _counts(client)
    return {k: v - before.get(k, 0.0) for k, v in after.items() if v - before.get(k, 0.0)}


def _basic(user: str, secret: str) -> dict[str, str]:
    return {"Authorization": f"Basic {base64.b64encode(f'{user}:{secret}'.encode()).decode()}"}


def _click_form(*, sign: str) -> dict[str, str]:
    return {
        "click_trans_id": "9001",
        "service_id": CLICK_SERVICE_ID,
        "click_paydoc_id": "5001",
        "merchant_trans_id": "T0000001",
        "amount": "50000.00",
        "action": "0",
        "error": "0",
        "error_note": "Success",
        "sign_time": "2026-10-01 10:00:00",
        "sign_string": sign,
    }


# ---------- Click ----------


async def test_three_bad_click_signatures_count_three(integration_client: AsyncClient) -> None:
    before = await _counts(integration_client)
    for _ in range(3):
        r = await integration_client.post(
            "/api/v1/payments/click/prepare", data=_click_form(sign="0" * 32)
        )
        assert r.json()["error"] == -1
    assert await _delta(integration_client, before) == {("click", "signature"): 3.0}


async def test_click_unknown_service_counts_as_signature(integration_client: AsyncClient) -> None:
    before = await _counts(integration_client)
    form = _click_form(sign="0" * 32) | {"service_id": "1"}
    r = await integration_client.post("/api/v1/payments/click/prepare", data=form)
    assert r.json()["error"] == -1
    assert await _delta(integration_client, before) == {("click", "signature"): 1.0}


async def test_click_malformed_bodies_count_once_each(integration_client: AsyncClient) -> None:
    before = await _counts(integration_client)
    prepare = "/api/v1/payments/click/prepare"
    # not a form at all
    assert (await integration_client.post(prepare, json={"a": 1})).json()["error"] == -8
    # a form missing sign_string
    form = _click_form(sign="x")
    del form["sign_string"]
    assert (await integration_client.post(prepare, data=form)).json()["error"] == -8
    # a non-numeric id
    form = _click_form(sign="x") | {"click_trans_id": "abc"}
    assert (await integration_client.post(prepare, data=form)).json()["error"] == -8
    # a stray GET
    assert (await integration_client.get(prepare)).json()["error"] == -8
    assert await _delta(integration_client, before) == {("click", "malformed"): 4.0}


async def test_click_good_signature_wrong_action_counts_nothing(
    integration_client: AsyncClient,
) -> None:
    parts = ("9001", CLICK_SERVICE_ID, CLICK_SECRET, "T0000001", "50000.00", "1", "t")
    sign = hashlib.md5("".join(parts).encode()).hexdigest()
    form = _click_form(sign=sign) | {"action": "1", "sign_time": "t"}
    before = await _counts(integration_client)
    r = await integration_client.post("/api/v1/payments/click/prepare", data=form)
    assert r.json()["error"] == -3
    assert await _delta(integration_client, before) == {}


# ---------- Payme ----------

PAYME = "/api/v1/payments/payme/merchant"


async def test_payme_rejections_count_once_each(integration_client: AsyncClient) -> None:
    good = _basic("Paycom", PAYME_KEY)
    before = await _counts(integration_client)

    # -32504: wrong key, wrong login, no header
    for headers in (_basic("Paycom", "nope"), _basic("Other", PAYME_KEY), {}):
        r = await integration_client.post(PAYME, headers=headers, json={"method": "x"})
        assert r.json()["error"]["code"] == -32504
    # -32700: not JSON
    r = await integration_client.post(PAYME, headers=good, content=b"{not json")
    assert r.json()["error"]["code"] == -32700
    # -32700: nested deep enough to raise RecursionError in the JSON parser
    r = await integration_client.post(PAYME, headers=good, content=b"[" * 200_000 + b"]" * 200_000)
    assert (r.status_code, r.json()["error"]["code"]) == (200, -32700)
    # -32600: envelope without a method; params not an object
    r = await integration_client.post(PAYME, headers=good, json={"id": 1})
    assert r.json()["error"]["code"] == -32600
    r = await integration_client.post(
        PAYME, headers=good, json={"method": "CheckTransaction", "params": [], "id": 1}
    )
    assert r.json()["error"]["code"] == -32600
    # -32600 raised by a handler's parameter extractor (amount missing)
    r = await integration_client.post(
        PAYME,
        headers=good,
        json={"method": "CheckPerformTransaction", "params": {"account": {}}, "id": 1},
    )
    assert r.json()["error"]["code"] == -32600

    assert await _delta(integration_client, before) == {
        ("payme", "auth"): 3.0,
        ("payme", "malformed"): 5.0,
    }


async def test_payme_unknown_method_and_non_post_count_nothing(
    integration_client: AsyncClient,
) -> None:
    good = _basic("Paycom", PAYME_KEY)
    before = await _counts(integration_client)
    r = await integration_client.post(PAYME, headers=good, json={"method": "Nope", "id": 1})
    assert r.json()["error"]["code"] == -32601
    r = await integration_client.get(PAYME)
    assert r.json()["error"]["code"] == -32300
    assert await _delta(integration_client, before) == {}


# ---------- Uzum ----------

UZUM = "/api/v1/payments/uzum"


async def test_uzum_rejections_count_once_each(integration_client: AsyncClient) -> None:
    good = _basic(UZUM_LOGIN, UZUM_PASSWORD)
    body = {"serviceId": UZUM_SERVICE_ID, "timestamp": 1, "params": {}}
    before = await _counts(integration_client)

    # 10001: wrong password, no header
    for headers in (_basic(UZUM_LOGIN, "nope"), {}):
        r = await integration_client.post(f"{UZUM}/check", headers=headers, json=body)
        assert (r.status_code, r.json()["errorCode"]) == (400, 10001)
    # 10002: not JSON, a JSON array, a body nested deep enough to raise RecursionError
    for raw in (b"{nope", b"[1]", b"[" * 200_000 + b"]" * 200_000):
        r = await integration_client.post(f"{UZUM}/check", headers=good, content=raw)
        assert (r.status_code, r.json()["errorCode"]) == (400, 10002)
    # 10005: a missing field, from the endpoint's own extractor
    r = await integration_client.post(f"{UZUM}/check", headers=good, json=body)
    assert (r.status_code, r.json()["errorCode"]) == (400, 10005)
    r = await integration_client.post(
        f"{UZUM}/status", headers=good, json={"serviceId": UZUM_SERVICE_ID}
    )
    assert (r.status_code, r.json()["errorCode"]) == (400, 10005)

    assert await _delta(integration_client, before) == {
        ("uzum", "auth"): 2.0,
        ("uzum", "malformed"): 5.0,
    }


async def test_uzum_foreign_service_id_and_non_post_count_nothing(
    integration_client: AsyncClient,
) -> None:
    good = _basic(UZUM_LOGIN, UZUM_PASSWORD)
    before = await _counts(integration_client)
    r = await integration_client.post(
        f"{UZUM}/status", headers=good, json={"serviceId": 1, "transId": "t"}
    )
    assert r.json()["errorCode"] == 10006
    assert (await integration_client.get(f"{UZUM}/status")).json()["errorCode"] == 10003
    assert await _delta(integration_client, before) == {}
