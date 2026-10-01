"""Waxpeer's purchase side: buy one listing, read trades back by ``project_id``, balance.

Shapes recorded from real purchases on 2026-09-28 (spec §8.1): ``buy-one-p2p`` answers at
once with Waxpeer's trade id; ``check-many-project-id`` reports ``status`` 0 → 2 → 4, with
``release_date`` appearing at 4 only once the buyer accepts, and 6 + ``reason`` when the
offer fails. ``send_until`` is an epoch string, ``release_date`` ISO 8601.

Errors are classified, never lumped as "sold out" (ruling R6):

- ``WaxpeerBuyRefusedError`` — ``buy-one-p2p`` answered 200 ``success: false``.
- ``WaxpeerForbiddenError`` — HTTP 403, the key's IP whitelist: a config error.
- ``WaxpeerRateLimitedError`` — HTTP 429 (a ``WaxpeerUnavailableError``).
- ``WaxpeerUnavailableError`` — network failure or an answer we cannot read: a buy may
  have happened; resolve it by :meth:`WaxpeerTradeClient.check_project_ids`, never by
  buying again. It is **not** a ``WaxpeerError``.
- ``WaxpeerError(status=…)`` — any other HTTP error status (5xx included).

Every call is counted (``csmarket_waxpeer_calls_total``) and logged as
``skins.waxpeer.call`` with ``endpoint``, ``outcome`` and ``status`` only: the key, the
trade link's ``partner`` / ``token`` and the buyer's Steam ID travel in the query string
or the body, so neither a URL nor a body is ever logged.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from csmarket.core.config import Settings, get_settings
from csmarket.core.logging import get_logger
from csmarket.core.metrics import WaxpeerEndpoint, WaxpeerOutcome, record_waxpeer_call
from csmarket.core.redis import get_redis
from csmarket.modules.skins.waxpeer import (
    QueryValue,
    WaxpeerClient,
    WaxpeerError,
    WaxpeerRateLimitedError,
    WaxpeerUnavailableError,
)

log = get_logger("csmarket.skins.waxpeer")

#: ``check-many-project-id`` reads at most this many ids per call.
LOOKUP_MAX_IDS = 100


class WaxpeerBuyRefusedError(WaxpeerError):
    """``buy-one-p2p`` said no (sold, price moved, balance…) with HTTP 200.

    Attributes:
        new_price_units: The price Waxpeer would now accept, when it named one. Never
            accepted blindly (ruling R4).
    """

    def __init__(self, message: str, *, new_price_units: int | None, body: str = "") -> None:
        """Keep Waxpeer's message, the raw answer and the price it would now accept."""
        super().__init__(message, status=200, body=body)
        self.new_price_units = new_price_units


class WaxpeerForbiddenError(WaxpeerError):
    """HTTP 403: this host's IP is not on the key's whitelist. A config error, not a refusal."""

    def __init__(self, message: str = "forbidden", *, body: str = "") -> None:
        """Always ``status=403``."""
        super().__init__(message, status=403, body=body)


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class WaxpeerBuy(_Frozen):
    """A purchase Waxpeer accepted: its trade id and the price it charged (1000 = $1)."""

    id: int
    price_units: int


class WaxpeerSeller(_Frozen):
    """The seller as a trade entry shows them; no Steam ID is kept."""

    name: str | None
    avatar_url: str | None
    level: int | None
    joined_at: datetime | None


class WaxpeerTrade(_Frozen):
    """One trade as ``check-many-project-id`` reports it.

    ``status`` is Waxpeer's code (0 → 2 → 4 sent / accepted, 6 failed), −1 when
    unparsable. The buyer's ``for_steamid64`` is dropped at parse time.
    """

    id: int
    project_id: str
    status: int
    trade_id: str | None
    done: bool
    reason: str | None
    release_date: datetime | None
    is_released: bool
    send_until: datetime | None
    price_units: int
    penalties: dict[str, Any] | None  # Any: Waxpeer's penalty document, stored as received
    escrow_status: str | None
    seller: WaxpeerSeller


def _strict_int(raw: object) -> int | None:
    """An ``int`` or a numeric string as ``int``; ``None`` for anything else (bools too)."""
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str):
        try:
            return int(raw.strip())
        except ValueError:
            return None
    return None


def _epoch(raw: object) -> datetime | None:
    """Epoch seconds (``int`` or numeric string) as an aware UTC datetime."""
    seconds = _strict_int(raw)
    if seconds is None or seconds <= 0:
        return None
    try:
        return datetime.fromtimestamp(seconds, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None


def _iso(raw: object) -> datetime | None:
    """ISO 8601 with an offset (``Z`` included) in UTC; a naive or bad value is ``None``."""
    if not isinstance(raw, str) or not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo is not None else None


def _text(raw: object) -> str | None:
    """A non-empty value as text, else ``None``."""
    if raw is None or isinstance(raw, bool):
        return None
    text = str(raw).strip()
    return text or None


def _flag(raw: object) -> bool:
    """Waxpeer booleans: ``true`` / ``1`` / ``"true"``; anything else is ``False``."""
    if isinstance(raw, str):
        return raw.strip().lower() in ("true", "1")
    return raw is True or (_strict_int(raw) == 1)


def _seller(raw: Mapping[str, object]) -> WaxpeerSeller:
    avatar = raw.get("seller_avatar")
    return WaxpeerSeller(
        name=_text(raw.get("seller_name")),
        avatar_url=avatar if isinstance(avatar, str) and avatar else None,
        level=_strict_int(raw.get("seller_steam_level")),
        joined_at=_epoch(raw.get("seller_steam_joined")),
    )


def parse_trade(raw: dict[str, Any]) -> WaxpeerTrade:  # Any: one entry of Waxpeer's JSON
    """One ``trades[]`` entry → :class:`WaxpeerTrade`; Steam IDs are not carried over.

    ``send_until`` / ``seller_steam_joined`` are epoch seconds (string or int);
    ``release_date`` is ISO 8601; empty ``penalties`` become ``None``.
    """
    penalties = raw.get("penalties")
    status = _strict_int(raw.get("status"))
    return WaxpeerTrade(
        id=_strict_int(raw.get("id")) or 0,
        project_id=_text(raw.get("project_id")) or "",
        status=-1 if status is None else status,
        trade_id=_text(raw.get("trade_id")),
        done=_flag(raw.get("done")),
        reason=_text(raw.get("reason")),
        release_date=_iso(raw.get("release_date")),
        is_released=_flag(raw.get("is_released")),
        send_until=_epoch(raw.get("send_until")),
        price_units=_strict_int(raw.get("price")) or 0,
        penalties=penalties if isinstance(penalties, dict) and penalties else None,
        escrow_status=_text(raw.get("escrow_status")),
        seller=_seller(raw),
    )


def _new_price_units(body: str) -> int | None:
    """``new_price`` from a refusal's raw body, when it is a whole number."""
    try:
        parsed = json.loads(body) if body else None
    except ValueError:
        return None
    return _strict_int(parsed.get("new_price")) if isinstance(parsed, dict) else None


def _classify(exc: BaseException) -> tuple[WaxpeerOutcome, int | None]:
    """The metric outcome and HTTP status of a failed call."""
    if isinstance(exc, WaxpeerForbiddenError):
        return "forbidden", 403
    if isinstance(exc, WaxpeerRateLimitedError):
        return "rate_limited", 429
    if isinstance(exc, WaxpeerUnavailableError):
        return "unavailable", None
    if isinstance(exc, WaxpeerError):
        return ("refused" if exc.status == 200 else "error"), exc.status
    return "error", None


def _record(endpoint: WaxpeerEndpoint, outcome: WaxpeerOutcome, status: int | None) -> None:
    record_waxpeer_call(endpoint, outcome)
    if outcome == "ok":
        log.info("skins.waxpeer.call", endpoint=endpoint, outcome=outcome, status=status)
    else:
        log.warning("skins.waxpeer.call", endpoint=endpoint, outcome=outcome, status=status)


@asynccontextmanager
async def _metered(endpoint: WaxpeerEndpoint) -> AsyncIterator[None]:
    """Count and log the call made in the block, however it ends; exceptions propagate."""
    try:
        yield
    except asyncio.CancelledError:
        # Our own cancellation (shutdown, a timeout around us), not Waxpeer's answer: not
        # counted. A cancelled buy is still unknown — the caller resolves it by lookup.
        raise
    except BaseException as exc:
        outcome, status = _classify(exc)
        _record(endpoint, outcome, status)
        raise
    _record(endpoint, "ok", 200)


@runtime_checkable
class TradeClient(Protocol):
    """What the order worker and the trade sweeps need from Waxpeer (real or fake)."""

    async def buy_one_p2p(
        self, *, item_id: int, price_units: int, partner: int, token: str, project_id: str
    ) -> WaxpeerBuy:
        """Buy one listing for at most ``price_units``, sent to the buyer's trade link."""
        ...

    async def check_project_ids(self, project_ids: Sequence[str]) -> list[WaxpeerTrade]:
        """Trades for up to 100 of our ``project_id`` values; unknown ids are absent."""
        ...

    async def balance_units(self) -> int:
        """Our Waxpeer wallet balance (1000 = $1)."""
        ...

    async def search_listings(
        self, names: Sequence[str]
    ) -> dict[str, list[dict[str, Any]]]:  # Any: Waxpeer listing JSON, read by the caller
        """Live listings by Waxpeer name (M2's search-by-name)."""
        ...


class WaxpeerTradeClient(WaxpeerClient):
    """The purchase endpoints on top of :class:`WaxpeerClient`'s transport."""

    async def _call(
        self, path: str, params: Mapping[str, QueryValue] | None = None
    ) -> dict[str, Any]:  # Any: Waxpeer's JSON body, narrowed by each caller
        """``GET {path}`` with HTTP 403 raised as :class:`WaxpeerForbiddenError`."""
        try:
            return await self._request("GET", path, params=params)
        except WaxpeerError as exc:
            if exc.status == 403:
                raise WaxpeerForbiddenError(body=exc.body) from exc
            raise

    async def buy_one_p2p(
        self, *, item_id: int, price_units: int, partner: int, token: str, project_id: str
    ) -> WaxpeerBuy:
        """``GET /v1/buy-one-p2p``: buy ``item_id`` for at most ``price_units``.

        Waxpeer's seller sends the offer to the trade link ``partner`` / ``token``;
        ``project_id`` is our order id, the key every later lookup reads by.

        Raises:
            WaxpeerBuyRefusedError: Waxpeer said no; ``new_price_units`` if the price moved.
            WaxpeerForbiddenError: HTTP 403 — this host is not whitelisted.
            WaxpeerRateLimitedError: HTTP 429.
            WaxpeerUnavailableError: No key, a transport failure or an unreadable answer —
                the buy may have happened; resolve by :meth:`check_project_ids`.
            WaxpeerError: Any other HTTP error status (``status`` set).
        """
        params: dict[str, QueryValue] = {
            "item_id": item_id,
            "price": price_units,
            "partner": partner,
            "token": token,
            "project_id": project_id,
        }
        async with _metered("buy"):
            try:
                body = await self._call("/buy-one-p2p", params)
            except WaxpeerError as exc:
                if exc.status != 200:
                    raise
                raise WaxpeerBuyRefusedError(
                    str(exc), new_price_units=_new_price_units(exc.body), body=exc.body
                ) from exc
            bought_id = _strict_int(body.get("id"))
            charged = _strict_int(body.get("price"))
            if bought_id is None or bought_id <= 0 or charged is None:
                raise WaxpeerUnavailableError("unexpected body")
        return WaxpeerBuy(id=bought_id, price_units=charged)

    async def check_project_ids(self, project_ids: Sequence[str]) -> list[WaxpeerTrade]:
        """``GET /v1/check-many-project-id?id=…&id=…`` for up to 100 ``project_id`` values.

        An id Waxpeer has never seen is simply absent (``[]`` for all-unknown). More than
        100 ids is refused rather than truncated: a dropped id would read as "never
        bought". An answer without a readable ``trades`` list, or with an entry lacking a
        positive ``id`` or a ``project_id``, is an outage, not "absent".

        Raises:
            ValueError: More than :data:`LOOKUP_MAX_IDS` ids.
            TypeError: One bare string instead of a sequence of ids.
            WaxpeerForbiddenError: HTTP 403.
            WaxpeerRateLimitedError: HTTP 429.
            WaxpeerUnavailableError: No key, a transport failure or an unreadable answer.
            WaxpeerError: A 200 ``success: false`` (``status=200``) or another HTTP status.
        """
        if isinstance(project_ids, str):
            raise TypeError("project_ids must be a sequence of ids, not one string")
        if len(project_ids) > LOOKUP_MAX_IDS:
            raise ValueError(f"at most {LOOKUP_MAX_IDS} project ids per lookup")
        if not project_ids:
            return []
        async with _metered("lookup"):
            body = await self._call("/check-many-project-id", {"id": list(project_ids)})
            raw = body.get("trades")
            if not isinstance(raw, list) or not all(isinstance(t, dict) for t in raw):
                raise WaxpeerUnavailableError("unexpected body")
            trades = [parse_trade(t) for t in raw]
            # An entry we cannot tie to an order would leave that order looking "never
            # bought" — and a rebuy. The whole answer is unreadable instead.
            if any(t.id <= 0 or not t.project_id for t in trades):
                raise WaxpeerUnavailableError("unexpected body")
        return trades

    async def balance_units(self) -> int:
        """``GET /v1/user`` → ``user.wallet``, our balance in units (1000 = $1).

        Raises:
            WaxpeerForbiddenError: HTTP 403.
            WaxpeerRateLimitedError: HTTP 429.
            WaxpeerUnavailableError: No key, a transport failure, or no integer
                ``user.wallet`` (never a guessed balance).
            WaxpeerError: A 200 ``success: false`` or another HTTP error status.
        """
        async with _metered("balance"):
            body = await self._call("/user")
            user = body.get("user")
            wallet = user.get("wallet") if isinstance(user, dict) else None
            if not isinstance(wallet, int) or isinstance(wallet, bool):
                # The shape only: this answer carries the account's own trade link.
                log.warning("skins.waxpeer.unexpected_wallet", wallet_type=type(wallet).__name__)
                raise WaxpeerUnavailableError("unexpected body")
        return wallet


def trade_client(settings: Settings | None = None) -> TradeClient:
    """The process's Waxpeer purchase client, with the buy timeout.

    The dev fake (Redis-backed, ruling R13) when ``waxpeer_fake`` is on outside prod: the
    worker's buys and every scheduler sweep build their client here.
    """
    settings = settings or get_settings()
    # Imported here: the fake builds on this module's models.
    from csmarket.modules.skins import waxpeer_fake

    if waxpeer_fake.fake_active(settings):
        return waxpeer_fake.FakeTradeClient(get_redis())
    return WaxpeerTradeClient(
        api_key=settings.waxpeer_api_key,
        base_url=settings.waxpeer_base_url,
        timeout_seconds=settings.waxpeer_buy_timeout_seconds,
    )


__all__ = [
    "LOOKUP_MAX_IDS",
    "TradeClient",
    "WaxpeerBuy",
    "WaxpeerBuyRefusedError",
    "WaxpeerForbiddenError",
    "WaxpeerSeller",
    "WaxpeerTrade",
    "WaxpeerTradeClient",
    "parse_trade",
    "trade_client",
]
