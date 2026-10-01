"""A scriptable :class:`~csmarket.modules.skins.api.TradeClient` for the orders suites.

Every call is counted; each endpoint answers what the test scripted last:

- ``lookup_returns([...])`` / ``lookup_raises(exc)`` / ``lookup_fails_for(id, exc)`` —
  ``check_project_ids`` (only the scripted trades whose ``project_id`` was asked for come
  back);
- ``buy_returns(WaxpeerBuy)`` / ``buy_raises(exc)`` — ``buy_one_p2p``; ``refuse(listing_id,
  exc)`` makes one listing raise whatever the default script says. With nothing scripted a
  buy succeeds at the offered price;
- ``balance_returns(units)`` / ``balance_raises(exc)`` — ``balance_units``;
- ``listings(name, [(listing_id, units), ...])`` — ``search_listings`` (auto offers);
- ``before_buy`` / ``before_lookup`` — awaited at the start of every buy / lookup (a
  test's hook to move the rows during the call).

Import as ``from tests.integration.fake_trade_client import FakeTradeClient``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from csmarket.modules.skins.api import WaxpeerBuy, WaxpeerSeller, WaxpeerTrade


def waxpeer_trade(project_id: str, *, status: int = 0, **overrides: Any) -> WaxpeerTrade:
    """One trade as a lookup reports it (``overrides`` replace any field)."""
    values: dict[str, Any] = {
        "id": 40_100_200,
        "project_id": project_id,
        "status": status,
        "trade_id": "7700112233" if status >= 2 else None,
        "done": status in (5, 6),
        "reason": None,
        "release_date": None,
        "is_released": False,
        "send_until": datetime(2026, 10, 2, 12, 30, tzinfo=UTC) + timedelta(minutes=30),
        "price_units": 12_345,
        "penalties": None,
        "escrow_status": None,
        "seller": WaxpeerSeller(name="redrawn_seller", avatar_url=None, level=9, joined_at=None),
    }
    values.update(overrides)
    return WaxpeerTrade(**values)


class FakeTradeClient:
    """Stands in for Waxpeer's purchase endpoints; see the module docstring."""

    def __init__(self) -> None:
        self._trades: list[WaxpeerTrade] = []
        self._lookup_error: BaseException | None = None
        self._lookup_failures: dict[str, BaseException] = {}
        self._buy: WaxpeerBuy | BaseException | None = None
        self._refused: dict[int, BaseException] = {}
        self._balance: int | BaseException = 10_000_000
        self._listings: dict[str, list[dict[str, Any]]] = {}
        self.lookup_calls = 0
        self.buy_calls = 0
        self.balance_calls = 0
        self.search_calls = 0
        #: ``(listing_id, price_units, project_id)`` of every buy that went through.
        self.bought: list[tuple[int, int, str]] = []
        self._next_id = 50_000_001
        #: Awaited at the start of every buy / lookup — a test's hook to move the rows.
        self.before_buy: Callable[[], Awaitable[None]] | None = None
        self.before_lookup: Callable[[], Awaitable[None]] | None = None

    # --- scripting ---------------------------------------------------------------------

    def lookup_returns(self, trades: Sequence[WaxpeerTrade]) -> None:
        """Lookups answer ``trades`` (filtered by the ids asked for)."""
        self._trades, self._lookup_error = list(trades), None

    def lookup_raises(self, exc: BaseException) -> None:
        """Lookups raise ``exc``."""
        self._lookup_error = exc

    def lookup_fails_for(self, project_id: str, exc: BaseException) -> None:
        """A lookup that asks for ``project_id`` raises ``exc``."""
        self._lookup_failures[project_id] = exc

    def buy_returns(self, bought: WaxpeerBuy) -> None:
        """Buys answer ``bought``."""
        self._buy = bought

    def buy_raises(self, exc: BaseException) -> None:
        """Buys raise ``exc``."""
        self._buy = exc

    def refuse(self, listing_id: int, exc: BaseException) -> None:
        """A buy of ``listing_id`` raises ``exc`` whatever else is scripted."""
        self._refused[listing_id] = exc

    def balance_returns(self, units: int) -> None:
        """``balance_units`` answers ``units``."""
        self._balance = units

    def balance_raises(self, exc: BaseException) -> None:
        """``balance_units`` raises ``exc``."""
        self._balance = exc

    def listings(
        self,
        name: str,
        offers: Sequence[tuple[int, int]],
        *,
        manual: Sequence[tuple[int, int]] = (),
    ) -> None:
        """``offers`` (and ``manual``, non-auto sellers) become the live listings of ``name``."""
        self._listings[name] = [
            {"item_id": listing_id, "price": units, "auto": True} for listing_id, units in offers
        ] + [{"item_id": listing_id, "price": units, "auto": False} for listing_id, units in manual]

    # --- TradeClient -------------------------------------------------------------------

    async def check_project_ids(self, project_ids: Sequence[str]) -> list[WaxpeerTrade]:
        """The scripted trades under ``project_ids``."""
        self.lookup_calls += 1
        if self.before_lookup is not None:
            await self.before_lookup()
        if self._lookup_error is not None:
            raise self._lookup_error
        wanted = set(project_ids)
        for project_id in wanted & self._lookup_failures.keys():
            raise self._lookup_failures[project_id]
        return [t for t in self._trades if t.project_id in wanted]

    async def buy_one_p2p(
        self, *, item_id: int, price_units: int, partner: int, token: str, project_id: str
    ) -> WaxpeerBuy:
        """The scripted answer; a plain success at ``price_units`` by default."""
        self.buy_calls += 1
        if self.before_buy is not None:
            await self.before_buy()
        refused = self._refused.get(item_id)
        if refused is not None:
            raise refused
        if isinstance(self._buy, BaseException):
            raise self._buy
        self.bought.append((item_id, price_units, project_id))
        if self._buy is not None:
            return self._buy
        self._next_id += 1
        return WaxpeerBuy(id=self._next_id, price_units=price_units)

    async def balance_units(self) -> int:
        """The scripted balance (plenty by default)."""
        self.balance_calls += 1
        if isinstance(self._balance, BaseException):
            raise self._balance
        return self._balance

    async def search_listings(
        self, names: Sequence[str]
    ) -> dict[str, list[dict[str, Any]]]:  # Any: raw Waxpeer listing rows
        """The scripted listings of each name asked for."""
        self.search_calls += 1
        return {name: list(self._listings.get(name, [])) for name in names}


__all__ = ["FakeTradeClient", "waxpeer_trade"]
