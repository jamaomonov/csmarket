"""Recorded Waxpeer catalogue shapes: the CSV snapshot, ``/v1/prices`` and live search.

The snapshot is consumed as a stream and must never be materialised; these tests feed it
through respx and assert on the parsed rows. The API key rides the ``api`` query parameter,
so nothing may log a URL or ``httpx`` exception text.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path

import httpx
import pytest
import respx
import structlog
from csmarket.core.logging import configure_logging
from csmarket.modules.skins import waxpeer
from csmarket.modules.skins.waxpeer import (
    WaxpeerClient,
    WaxpeerError,
    WaxpeerRateLimitedError,
    WaxpeerUnavailableError,
)

pytestmark = pytest.mark.asyncio

BASE = "https://api.waxpeer.test/v1"
HOST = "https://api.waxpeer.test"
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "skins"
REDLINE = "AK-47 | Redline (Field-Tested)"


def _client() -> WaxpeerClient:
    return WaxpeerClient(api_key="k", base_url=BASE, timeout_seconds=5)


class _Logs:
    """Live view of what was logged: structlog events and stdlib records alike."""

    def __init__(
        self, events: Sequence[Mapping[str, object]], caplog: pytest.LogCaptureFixture
    ) -> None:
        self._events = events
        self._caplog = caplog

    def lines(self) -> list[str]:
        return [str(e) for e in self._events] + [r.getMessage() for r in self._caplog.records]


@pytest.fixture
def logs(caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch) -> Iterator[_Logs]:
    """Read ``logs.lines()`` inside the test: it is empty again once the fixture closes.

    ``configure_logging`` is the production setup (it caps httpx's URL-logging at WARNING),
    so this checks what would really reach Loki.
    """
    configure_logging()
    # ``capture_logs`` only sees loggers that are not cached, and the module's ``log`` may
    # have been bound (and cached) by an earlier test in this process: swap in a fresh one.
    structlog.configure(cache_logger_on_first_use=False)
    monkeypatch.setattr(waxpeer, "log", structlog.get_logger("csmarket.skins.waxpeer"))
    with structlog.testing.capture_logs() as events, caplog.at_level(logging.INFO):
        yield _Logs(events, caplog)
    structlog.configure(cache_logger_on_first_use=True)


@respx.mock
async def test_snapshot_rows_are_parsed_from_csv() -> None:
    respx.get(f"{HOST}/v1/prices/snapshot").mock(
        return_value=httpx.Response(
            200,
            content=(FIXTURES / "snapshot.csv").read_bytes(),
            headers={"content-type": "text/csv; charset=utf-8"},
        )
    )
    rows = [row async for row in _client().iter_snapshot_rows()]
    assert len(rows) == 6
    assert rows[0].item_id == 53857957789
    assert rows[0].price_units == 27867
    assert rows[0].auto is True
    assert rows[2].auto is False
    assert rows[4].name == 'Sticker | Say "GG" (Holo)'
    sent = respx.calls.last.request
    assert sent.url.params["format"] == "csv"
    assert sent.url.params["game"] == "csgo"
    assert sent.url.params["api"] == "k"
    assert "include_hold" not in sent.url.params


@respx.mock
async def test_snapshot_503_raises_waxpeer_error() -> None:
    respx.get(f"{HOST}/v1/prices/snapshot").mock(return_value=httpx.Response(503, text="not ready"))
    with pytest.raises(WaxpeerError) as exc:
        _ = [row async for row in _client().iter_snapshot_rows()]
    assert exc.value.status == 503


@respx.mock
async def test_snapshot_429_is_rate_limited_and_an_outage() -> None:
    respx.get(f"{HOST}/v1/prices/snapshot").mock(
        return_value=httpx.Response(429, text="busy", headers={"Retry-After": "1"})
    )
    with pytest.raises(WaxpeerRateLimitedError) as exc:
        _ = [row async for row in _client().iter_snapshot_rows()]
    assert exc.value.retry_after_seconds == 1.0
    assert isinstance(exc.value, WaxpeerUnavailableError)


@respx.mock
async def test_snapshot_429_without_a_hint() -> None:
    respx.get(f"{HOST}/v1/prices/snapshot").mock(return_value=httpx.Response(429, text="busy"))
    with pytest.raises(WaxpeerRateLimitedError) as exc:
        _ = [row async for row in _client().iter_snapshot_rows()]
    assert exc.value.retry_after_seconds is None


@respx.mock
async def test_snapshot_network_failure_is_unavailable(logs: _Logs) -> None:
    respx.get(f"{HOST}/v1/prices/snapshot").mock(side_effect=httpx.ConnectTimeout("t"))
    with pytest.raises(WaxpeerUnavailableError, match="ConnectTimeout"):
        _ = [row async for row in _client().iter_snapshot_rows()]


@respx.mock
async def test_snapshot_without_required_columns_raises_once() -> None:
    respx.get(f"{HOST}/v1/prices/snapshot").mock(
        return_value=httpx.Response(200, text='item_id,name,price_units,auto\n1,"A",100,true\n')
    )
    with pytest.raises(WaxpeerError, match="columns"):
        _ = [row async for row in _client().iter_snapshot_rows()]


@pytest.mark.parametrize("body", ["", "\n\n"])
@respx.mock
async def test_snapshot_empty_200_is_unavailable(body: str) -> None:
    respx.get(f"{HOST}/v1/prices/snapshot").mock(return_value=httpx.Response(200, text=body))
    with pytest.raises(WaxpeerUnavailableError, match="unexpected body"):
        _ = [row async for row in _client().iter_snapshot_rows()]


@respx.mock
async def test_snapshot_rows_with_an_unknown_price_are_skipped_and_counted(
    logs: _Logs,
) -> None:
    body = (
        "item_id,name,price,auto,inspect\n"
        '1,"A",,true,x\n'
        '2,"A",000000000000,true,x\n'
        'zz,"A",000000000500,true,x\n'
        '3,"A",000000000500,true,x\n'
    )
    respx.get(f"{HOST}/v1/prices/snapshot").mock(return_value=httpx.Response(200, text=body))
    rows = [row async for row in _client().iter_snapshot_rows()]
    assert [(r.item_id, r.price_units) for r in rows] == [(3, 500)]
    done = [line for line in logs.lines() if "waxpeer.snapshot.done" in line]
    assert len(done) == 1
    assert "'rows': 1" in done[0]
    assert "'bad_rows': 3" in done[0]


@respx.mock
async def test_prices_returns_items() -> None:
    respx.get(f"{HOST}/v1/prices").mock(
        return_value=httpx.Response(200, content=(FIXTURES / "prices.json").read_bytes())
    )
    items = await _client().prices()
    assert len(items) == 4
    assert items[0]["type"] == "Rifles"
    params = respx.calls.last.request.url.params
    assert params["minified"] == "0"
    assert params["game"] == "csgo"


@respx.mock
async def test_prices_http_error_is_a_waxpeer_error() -> None:
    respx.get(f"{HOST}/v1/prices").mock(return_value=httpx.Response(502, text="bad gateway"))
    with pytest.raises(WaxpeerError):
        await _client().prices()


@respx.mock
async def test_prices_429_is_rate_limited() -> None:
    respx.get(f"{HOST}/v1/prices").mock(
        return_value=httpx.Response(429, text="slow", headers={"Retry-After": "2.5"})
    )
    with pytest.raises(WaxpeerRateLimitedError) as exc:
        await _client().prices()
    assert exc.value.retry_after_seconds == 2.5


@respx.mock
async def test_prices_timeout_is_unavailable() -> None:
    respx.get(f"{HOST}/v1/prices").mock(side_effect=httpx.ReadTimeout("t"))
    with pytest.raises(WaxpeerUnavailableError):
        await _client().prices()


@respx.mock
async def test_prices_unreadable_200_is_unavailable() -> None:
    respx.get(f"{HOST}/v1/prices").mock(return_value=httpx.Response(200, text="<html>x</html>"))
    with pytest.raises(WaxpeerUnavailableError):
        await _client().prices()


@respx.mock
async def test_search_listings_asks_for_delivery_details_and_never_hold() -> None:
    respx.get(f"{HOST}/v2/search-items-by-name").mock(
        return_value=httpx.Response(200, content=(FIXTURES / "search_v2.json").read_bytes())
    )
    items = await _client().search_listings([REDLINE])
    assert len(items[REDLINE]) == 3
    params = respx.calls.last.request.url.params
    assert params["delivery_details"] == "1"
    assert params["minified"] == "0"
    assert params["game"] == "csgo"
    assert params.get_list("name") == [REDLINE]
    assert "include_hold" not in params


@respx.mock
async def test_search_listings_sends_at_most_50_names() -> None:
    respx.get(f"{HOST}/v2/search-items-by-name").mock(
        return_value=httpx.Response(200, json={"success": True, "items": {}})
    )
    assert await _client().search_listings([f"n{i}" for i in range(80)]) == {}
    assert len(respx.calls.last.request.url.params.get_list("name")) == 50


@respx.mock
async def test_search_listings_429_is_rate_limited() -> None:
    respx.get(f"{HOST}/v2/search-items-by-name").mock(
        return_value=httpx.Response(
            429, json={"success": False, "msg": "Too many", "msBeforeNext": 2500}
        )
    )
    with pytest.raises(WaxpeerRateLimitedError) as exc:
        await _client().search_listings(["x"])
    assert exc.value.retry_after_seconds == 2.5


@respx.mock
async def test_search_listings_http_error_is_a_waxpeer_error() -> None:
    respx.get(f"{HOST}/v2/search-items-by-name").mock(return_value=httpx.Response(500, text="x"))
    with pytest.raises(WaxpeerError):
        await _client().search_listings(["x"])


@respx.mock
async def test_search_listings_network_failure_is_unavailable() -> None:
    respx.get(f"{HOST}/v2/search-items-by-name").mock(side_effect=httpx.ConnectError("c"))
    with pytest.raises(WaxpeerUnavailableError):
        await _client().search_listings(["x"])


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="<html>Just a moment...</html>"),
        httpx.Response(200, json=[]),
        httpx.Response(200, json="ok"),
    ],
)
@respx.mock
async def test_search_listings_unreadable_200_is_unavailable(response: httpx.Response) -> None:
    respx.get(f"{HOST}/v2/search-items-by-name").mock(return_value=response)
    with pytest.raises(WaxpeerUnavailableError):
        await _client().search_listings(["x"])


@respx.mock
async def test_no_key_means_no_traffic() -> None:
    route = respx.get(url__startswith="https://api.waxpeer.test/")
    client = WaxpeerClient(api_key="", base_url=BASE, timeout_seconds=5)
    with pytest.raises(WaxpeerUnavailableError):
        _ = [row async for row in client.iter_snapshot_rows()]
    with pytest.raises(WaxpeerUnavailableError):
        await client.prices()
    with pytest.raises(WaxpeerUnavailableError):
        await client.search_listings([REDLINE])
    assert not route.called


@respx.mock
async def test_no_log_line_carries_the_key(logs: _Logs) -> None:
    respx.get(url__startswith=f"{BASE}/prices").mock(return_value=httpx.Response(500, text="boom"))
    respx.get(f"{HOST}/v2/search-items-by-name").mock(side_effect=httpx.ConnectTimeout("t"))
    respx.get(f"{HOST}/v1/prices/snapshot").mock(return_value=httpx.Response(503, text="x"))
    client = WaxpeerClient(api_key="SECRET-KEY-123", base_url=BASE, timeout_seconds=5)
    with pytest.raises(WaxpeerError):
        await client.prices()
    with pytest.raises(WaxpeerUnavailableError):
        await client.search_listings(["x"])
    with pytest.raises(WaxpeerError):
        _ = [row async for row in client.iter_snapshot_rows()]
    assert any("waxpeer.request" in line for line in logs.lines())
    assert all("SECRET-KEY-123" not in line for line in logs.lines())
