"""Contract tests for the Resend email client (respx; never the real api.resend.com)."""

from __future__ import annotations

import httpx
import pytest
import respx
from csmarket.modules.notifications.resend import (
    EmailRejectedError,
    EmailRetryableError,
    ResendClient,
)

BASE = "https://resend.test"
KEY = "re_fake_key_never_real"
#: A fake recipient: the address must never reach a log line either.
TO = "buyer@example.test"


def _client(key: str = KEY) -> ResendClient:
    return ResendClient(key, BASE, 5, sender="CS Market <noreply@csmarket.uz>")


async def _send(client: ResendClient | None = None, *, key: str = "outbox-1") -> str:
    return await (client or _client()).send(
        to=TO, subject="Hi", html="<b>Hi</b>", text="Hi", idempotency_key=key
    )


@respx.mock
async def test_success_returns_the_message_id_and_sends_key_and_idempotency() -> None:
    route = respx.post(f"{BASE}/emails").respond(200, json={"id": "msg_123"})
    assert await _send(key="b3f1c0de-0000-4000-8000-000000000001") == "msg_123"
    sent = route.calls.last.request
    assert sent.headers["Authorization"] == f"Bearer {KEY}"
    assert sent.headers["Idempotency-Key"] == "b3f1c0de-0000-4000-8000-000000000001"
    body = sent.read().decode()
    assert TO in body
    assert "CS Market <noreply@csmarket.uz>" in body


@pytest.mark.parametrize("status", [429, 500, 502, 503])
@respx.mock
async def test_rate_limit_and_server_errors_are_retryable(status: int) -> None:
    respx.post(f"{BASE}/emails").respond(status, json={"message": "later"})
    with pytest.raises(EmailRetryableError) as caught:
        await _send()
    assert caught.value.code == f"http_{status}"


@pytest.mark.parametrize(
    ("error", "code"),
    [(httpx.ConnectError("x"), "network"), (httpx.ReadTimeout("x"), "timeout")],
)
@respx.mock
async def test_network_failures_are_retryable(error: Exception, code: str) -> None:
    respx.post(f"{BASE}/emails").mock(side_effect=error)
    with pytest.raises(EmailRetryableError) as caught:
        await _send()
    assert caught.value.code == code


@pytest.mark.parametrize("status", [400, 403, 422])
@respx.mock
async def test_other_client_errors_are_rejected(status: int) -> None:
    respx.post(f"{BASE}/emails").respond(status, json={"message": "bad address"})
    with pytest.raises(EmailRejectedError) as caught:
        await _send()
    assert caught.value.code == f"http_{status}"


@respx.mock
async def test_an_answer_without_an_id_is_retryable() -> None:
    respx.post(f"{BASE}/emails").respond(200, json={})
    with pytest.raises(EmailRetryableError):
        await _send()


@respx.mock
async def test_without_a_key_nothing_is_sent() -> None:
    route = respx.post(f"{BASE}/emails").respond(200, json={"id": "x"})
    with pytest.raises(EmailRetryableError) as caught:
        await _send(_client(""))
    assert caught.value.code == "no_key"
    assert not route.called


@respx.mock
async def test_the_key_and_the_address_never_reach_the_logs(
    caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    respx.post(f"{BASE}/emails").respond(422, json={"message": f"bad {TO}"})
    with pytest.raises(EmailRejectedError) as caught:
        await _send()
    respx.post(f"{BASE}/emails").mock(side_effect=httpx.ConnectError(KEY))
    with pytest.raises(EmailRetryableError):
        await _send()
    out = capsys.readouterr()
    logged = caplog.text + out.out + out.err + str(caught.value)
    for leak in (KEY, TO, "bad address", "https://"):
        assert leak not in logged, leak
