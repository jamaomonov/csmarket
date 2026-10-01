"""Waxpeer ``POST /v1/check-tradelink`` (recorded shapes, respx).

Refusals arrive as HTTP 200 with ``success: false``; the API key rides the ``api`` query
parameter. The link below is a redrawn fake — never a real partner/token in tests.
"""

from __future__ import annotations

import httpx
import pytest
import respx
from csmarket.modules.skins.waxpeer import WaxpeerClient, WaxpeerError, WaxpeerUnavailableError

pytestmark = pytest.mark.asyncio
URL = "https://api.waxpeer.com/v1/check-tradelink"
LINK = "https://steamcommunity.com/tradeoffer/new/?partner=39734273&token=AbCdEf12"


def _client(key: str = "k") -> WaxpeerClient:
    return WaxpeerClient(api_key=key, base_url="https://api.waxpeer.com/v1", timeout_seconds=1)


@respx.mock
async def test_working_link_is_none_and_key_rides_the_query() -> None:
    route = respx.post(URL).mock(return_value=httpx.Response(200, json={"success": True}))
    assert await _client().check_tradelink(LINK) is None
    assert route.calls[0].request.url.params["api"] == "k"


@respx.mock
async def test_info_is_the_reason() -> None:
    respx.post(URL).mock(
        return_value=httpx.Response(200, json={"success": True, "info": "Inventory is private"})
    )
    assert await _client().check_tradelink(LINK) == "Inventory is private"


@respx.mock
async def test_success_false_is_a_reason_not_an_error() -> None:
    respx.post(URL).mock(
        return_value=httpx.Response(200, json={"success": False, "msg": "Invalid tradelink"})
    )
    assert await _client().check_tradelink(LINK) == "Invalid tradelink"


@respx.mock
async def test_http_error_raises() -> None:
    respx.post(URL).mock(return_value=httpx.Response(502, text="bad gateway"))
    with pytest.raises(WaxpeerError):
        await _client().check_tradelink(LINK)


async def test_no_key_is_unavailable_without_traffic() -> None:
    with pytest.raises(WaxpeerUnavailableError):
        await _client("").check_tradelink(LINK)


@respx.mock
async def test_timeout_is_unavailable() -> None:
    respx.post(URL).mock(side_effect=httpx.ConnectTimeout("t"))
    with pytest.raises(WaxpeerUnavailableError):
        await _client().check_tradelink(LINK)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, json=[]),
        httpx.Response(200, json=None),
        httpx.Response(200, json="ok"),
        httpx.Response(200, text="<html>maintenance</html>"),
    ],
)
@respx.mock
async def test_malformed_200_is_unavailable_not_a_reason(response: httpx.Response) -> None:
    respx.post(URL).mock(return_value=response)
    with pytest.raises(WaxpeerUnavailableError):
        await _client().check_tradelink(LINK)
