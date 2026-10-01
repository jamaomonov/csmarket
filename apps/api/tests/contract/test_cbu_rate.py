"""Contract tests for the CBU USD rate fetch (respx; never the real cbu.uz)."""

from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
import respx
from csmarket.modules.fx.cbu import CbuError, fetch_usd_uzs

URL = "https://cbu.test/ru/arkhiv-kursov-valyut/json/USD/"
ROW = {"Ccy": "USD", "Nominal": "1", "Rate": "12688.45", "Date": "30.09.2026"}


@respx.mock
async def test_reads_the_rate() -> None:
    respx.get(URL).mock(return_value=httpx.Response(200, json=[ROW]))
    assert await fetch_usd_uzs(url=URL, timeout=5) == Decimal("12688.45")


@respx.mock
async def test_nominal_divides() -> None:
    respx.get(URL).mock(
        return_value=httpx.Response(200, json=[ROW | {"Nominal": "10", "Rate": "126884.5"}])
    )
    assert await fetch_usd_uzs(url=URL, timeout=5) == Decimal("12688.45")


@pytest.mark.parametrize(
    "body",
    [
        [],
        {},
        [ROW | {"Ccy": "EUR"}],
        [ROW | {"Rate": "abc"}],
        [ROW | {"Rate": "0"}],
        [ROW | {"Rate": "999"}],
        [ROW | {"Rate": "100001"}],
        "<html>",
    ],
)
@respx.mock
async def test_refuses_what_is_not_a_plausible_usd_rate(body: object) -> None:
    respx.get(URL).mock(return_value=httpx.Response(200, json=body))
    with pytest.raises(CbuError):
        await fetch_usd_uzs(url=URL, timeout=5)


@respx.mock
async def test_http_and_network_errors_are_cbu_errors() -> None:
    respx.get(URL).mock(return_value=httpx.Response(503))
    with pytest.raises(CbuError):
        await fetch_usd_uzs(url=URL, timeout=5)
    respx.get(URL).mock(side_effect=httpx.ConnectTimeout("t"))
    with pytest.raises(CbuError):
        await fetch_usd_uzs(url=URL, timeout=5)


@respx.mock
async def test_a_non_json_body_is_a_cbu_error() -> None:
    respx.get(URL).mock(return_value=httpx.Response(200, content=b"<html>not json"))
    with pytest.raises(CbuError):
        await fetch_usd_uzs(url=URL, timeout=5)
