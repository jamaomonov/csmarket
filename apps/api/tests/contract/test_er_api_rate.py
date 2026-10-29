"""Contract tests for the fallback USD/UZS rate (open.er-api.com; respx, never the real one).

Used only when cbu.uz cannot be reached (it refuses our EU server, 2026-10-22).
"""

from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
import respx
from csmarket.modules.fx.cbu import CbuError
from csmarket.modules.fx.fallback import fetch_fallback_usd_uzs

URL = "https://er-api.test/v6/latest/USD"


@respx.mock
async def test_reads_uzs() -> None:
    respx.get(URL).mock(
        return_value=httpx.Response(200, json={"result": "success", "rates": {"UZS": 11983.753367}})
    )
    assert await fetch_fallback_usd_uzs(url=URL, timeout=5) == Decimal("11983.7534")


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500),
        httpx.Response(200, text="nope"),
        httpx.Response(200, json={"result": "error"}),
        httpx.Response(200, json={"result": "success", "rates": {}}),
        httpx.Response(200, json={"result": "success", "rates": {"UZS": 3}}),
    ],
)
@respx.mock
async def test_anything_else_is_an_error(response: httpx.Response) -> None:
    respx.get(URL).mock(return_value=response)
    with pytest.raises(CbuError):
        await fetch_fallback_usd_uzs(url=URL, timeout=5)


@respx.mock
async def test_a_network_failure_is_an_error() -> None:
    respx.get(URL).mock(side_effect=httpx.ConnectTimeout("slow"))
    with pytest.raises(CbuError):
        await fetch_fallback_usd_uzs(url=URL, timeout=5)
