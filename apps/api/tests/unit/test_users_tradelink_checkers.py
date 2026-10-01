"""The production trade-link checkers wired by ``users.routes.tradelink_checkers``."""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest
import respx
from csmarket.core import config as cfg
from csmarket.modules.skins.api import WaxpeerClient, WaxpeerUnavailableError
from csmarket.modules.users.routes import tradelink_checkers

STEAM = "https://api.steampowered.com/IEconService/GetTradeHoldDurations/v1/"
#: Fake token — never a real one in tests.
TOKEN = "AbCdEf12"


@pytest.fixture
def steam_key(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("CSMARKET_STEAM_API_KEY", "steam-test-key")
    cfg.get_settings.cache_clear()
    yield
    cfg.get_settings.cache_clear()


async def test_no_steam_key_means_no_hold_number_and_no_traffic() -> None:
    _, hold = tradelink_checkers()
    with respx.mock(assert_all_called=False) as mock:
        route = mock.get(STEAM)
        assert await hold.trade_hold_days("76561198000000001", TOKEN) is None
    assert not route.called


@pytest.mark.usefixtures("steam_key")
async def test_steam_key_asks_steam_for_the_hold() -> None:
    _, hold = tradelink_checkers()
    body = {"response": {"their_escrow": {"escrow_end_duration_seconds": 7 * 86400}}}
    with respx.mock() as mock:
        route = mock.get(STEAM).mock(return_value=httpx.Response(200, json=body))
        assert await hold.trade_hold_days("76561198000000001", TOKEN) == 7
    params = route.calls[0].request.url.params
    assert params["steamid_target"] == "76561198000000001"
    assert params["trade_offer_access_token"] == TOKEN


async def test_waxpeer_without_a_key_is_unavailable() -> None:
    waxpeer, _ = tradelink_checkers()
    assert isinstance(waxpeer, WaxpeerClient)
    with pytest.raises(WaxpeerUnavailableError):
        await waxpeer.check_tradelink(
            "https://steamcommunity.com/tradeoffer/new/?partner=1&token=x"
        )
