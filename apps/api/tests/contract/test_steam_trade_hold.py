"""Steam ``IEconService/GetTradeHoldDurations`` for a trade link (recorded shapes, respx)."""

from __future__ import annotations

import logging
from collections.abc import Iterator, Mapping, Sequence

import httpx
import pytest
import respx
import structlog
from csmarket.core.logging import configure_logging
from csmarket.modules.auth.steam import trade_hold_days

URL = "https://api.steampowered.com/IEconService/GetTradeHoldDurations/v1/"
#: A made-up trade-link token — never a real one in tests.
FAKE_TOKEN = "FakeTok9"


def _body(their_seconds: int) -> dict[str, object]:
    return {
        "response": {
            "my_escrow": {"escrow_end_duration_seconds": 0},
            "their_escrow": {"escrow_end_duration_seconds": their_seconds},
            "both_escrow": {"escrow_end_duration_seconds": their_seconds},
        }
    }


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
def logs(caplog: pytest.LogCaptureFixture) -> Iterator[_Logs]:
    """Read ``logs.lines()`` inside the test: it is empty again once the fixture closes.

    ``configure_logging`` is the production setup (it caps httpx's URL-logging at
    WARNING), so this checks what would really reach Loki.
    """
    configure_logging()
    # ``capture_logs`` only sees loggers that are not cached: an earlier test in this
    # process may have bound (and cached) one.
    structlog.configure(cache_logger_on_first_use=False)
    with structlog.testing.capture_logs() as events, caplog.at_level(logging.INFO):
        yield _Logs(events, caplog)
    structlog.configure(cache_logger_on_first_use=True)


def test_the_log_capture_is_live(logs: _Logs) -> None:
    """The fixture sees lines while the test runs, so the assertions below are not vacuous."""
    structlog.get_logger("csmarket.test").info("probe", token=FAKE_TOKEN)
    logging.getLogger("csmarket.test").warning("stdlib %s", FAKE_TOKEN)
    assert sum(FAKE_TOKEN in line for line in logs.lines()) == 2


@respx.mock
async def test_an_account_with_an_authenticator_has_no_hold(logs: _Logs) -> None:
    route = respx.get(URL).mock(return_value=httpx.Response(200, json=_body(0)))
    days = await trade_hold_days(76561198000000001, FAKE_TOKEN, api_key="K")
    assert days == 0
    sent = route.calls.last.request.url.params
    assert sent["steamid_target"] == "76561198000000001"
    assert sent["trade_offer_access_token"] == FAKE_TOKEN
    assert all(FAKE_TOKEN not in line for line in logs.lines())


@respx.mock
async def test_a_held_account_reports_whole_days(logs: _Logs) -> None:
    respx.get(URL).mock(return_value=httpx.Response(200, json=_body(7 * 86400)))
    assert await trade_hold_days(1, FAKE_TOKEN, api_key="K") == 7
    assert all(FAKE_TOKEN not in line for line in logs.lines())


@respx.mock
async def test_a_partial_day_rounds_up() -> None:
    respx.get(URL).mock(return_value=httpx.Response(200, json=_body(86400 + 1)))
    assert await trade_hold_days(1, FAKE_TOKEN, api_key="K") == 2


@respx.mock
async def test_a_body_without_their_escrow_is_unknown(logs: _Logs) -> None:
    respx.get(URL).mock(return_value=httpx.Response(200, json={"response": {}}))
    assert await trade_hold_days(1, FAKE_TOKEN, api_key="K") is None
    assert all(FAKE_TOKEN not in line for line in logs.lines())


@respx.mock
async def test_a_steam_error_raises(logs: _Logs) -> None:
    respx.get(URL).mock(return_value=httpx.Response(500))
    with pytest.raises(httpx.HTTPStatusError):
        await trade_hold_days(1, FAKE_TOKEN, api_key="K")
    assert all(FAKE_TOKEN not in line for line in logs.lines())


@respx.mock
async def test_the_call_is_counted_as_trade_link_by_default() -> None:
    from prometheus_client import REGISTRY

    def calls() -> float:
        labels = {
            "endpoint": "get_trade_hold_durations",
            "consumer": "trade_link",
            "outcome": "ok",
        }
        return REGISTRY.get_sample_value("csmarket_steam_web_api_calls_total", labels) or 0.0

    respx.get(URL).mock(return_value=httpx.Response(200, json=_body(0)))
    before = calls()
    await trade_hold_days(1, FAKE_TOKEN, api_key="K")
    assert calls() == before + 1
