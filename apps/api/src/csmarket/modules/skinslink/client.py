"""Skinslink merchant API client (https://docs.skinslink.com/llm, read 2026-10-06).

``X-Api-Key`` on every call; every answer is ``{success, message, data}``. Error bodies are
never logged (they can echo the request, the buyer's trade token included). Amounts are USD
as ``Decimal`` built from the JSON number's text, never through a float.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_DOWN, Decimal, InvalidOperation
from typing import Any, Literal, Protocol

import httpx

from csmarket.core.config import Settings
from csmarket.core.logging import get_logger
from csmarket.core.metrics import SkinslinkEndpoint, record_skinslink_call
from csmarket.modules.skinslink.stream import ItemsScanner

log = get_logger("csmarket.skinslink.client")

#: ``fail_reason`` of a failed purchase (Create Purchase).
PURCHASE_FAIL_REASONS = frozenset(
    {
        "insufficient_balance",
        "price_changed",
        "item_sold",
        "item_not_available",
        "duplicate_purchase",
        "item_specified_price_not_found",
        "provider_unavailable",
    }
)
#: Validation codes that mean the buyer's trade link cannot receive the skin.
LINK_ERROR_CODES = frozenset(
    {
        "trade_link_revoked",
        "trade_link_invalid",
        "trade_banned",
        "profile_private",
        "limited_account",
        "hold",
        "permissions",
        "hold_and_permissions",
    }
)
_RETRYABLE = frozenset({408, 500, 502, 503, 504})
_THREE_PLACES = Decimal("0.001")
#: Asks of one catalogue page while Skinslink rebuilds it, and the longest wait between.
_PAGE_TRIES = 4
_MAX_PAGE_WAIT = 30


class SkinslinkError(Exception):
    """Skinslink answered and said no: a 4xx, or a 200 with ``success: false``."""

    def __init__(self, message: str, *, status: int, code: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code


class SkinslinkForbiddenError(SkinslinkError):
    """HTTP 403: the merchant is disabled or this host is not whitelisted."""


class SkinslinkUnavailableError(Exception):
    """No answer worth reading: transport, 408/5xx, an unreadable body, or no key."""


class SkinslinkRateLimitedError(SkinslinkUnavailableError):
    """HTTP 429."""


@dataclass(frozen=True)
class CatalogueItem:
    """One item on Skinslink's sale list (Available Items, full + extended)."""

    id: str
    name: str
    price_usd: Decimal
    image_url: str | None
    phase: str | None
    float_value: float | None
    paint_seed: int | None
    inspect_url: str | None


@dataclass(frozen=True)
class CatalogueEvent:
    """One change of the sale list: ``upsert`` carries the full card, ``remove`` none."""

    type: Literal["upsert", "remove"]
    at: str
    id: str
    item: CatalogueItem | None


@dataclass(frozen=True)
class EventsPage:
    """A page of Catalogue Events; ``next`` is the cursor, kept exactly as sent."""

    since: str
    next: str
    more: bool
    reset: bool
    events: list[CatalogueEvent]


@dataclass(frozen=True)
class AvailablePage:
    """The whole sale list and the cursor to follow it from."""

    items: list[CatalogueItem]
    last_update_at: str


@dataclass(frozen=True)
class Purchase:
    """A purchase as Skinslink reports it (Create Purchase / Purchase Status)."""

    id: int
    merchant_tx_id: str | None
    status: str
    offer_id: str | None
    fail_reason: str | None
    amount_usd: Decimal | None
    asset_id: str | None
    hold_end_date: str | None


@dataclass(frozen=True)
class Balance:
    """The merchant balance, USD."""

    total: Decimal
    hold: Decimal
    available: Decimal


class SkinslinkPurchaseClient(Protocol):
    """What the order worker needs from Skinslink (the real client or a test double)."""

    async def purchase(
        self,
        *,
        asset_id: str,
        partner: int,
        token: str,
        merchant_tx_id: str,
        max_price_usd: Decimal,
    ) -> Purchase:
        """Buy ``asset_id`` for the trade link ``partner``/``token``."""
        ...

    async def purchase_status(self, *, merchant_tx_id: str) -> Purchase | None:
        """The purchase under ``merchant_tx_id``, or ``None`` when Skinslink has none."""
        ...


def _decimal(value: object) -> Decimal | None:
    """A JSON number (or numeric string) as ``Decimal`` via its text; ``None`` otherwise."""
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _str(value: object) -> str | None:
    """A non-empty string, or ``None``."""
    return value if isinstance(value, str) and value else None


# Any: one JSON object of Skinslink's, read field by field.
def _item(raw: Mapping[str, Any]) -> CatalogueItem | None:
    """A sale-list card, or ``None`` when its id, name or price is unusable."""
    raw_id = raw.get("id")
    item_id = str(raw_id) if isinstance(raw_id, int | str) and not isinstance(raw_id, bool) else ""
    name = _str(raw.get("name"))
    price = _decimal(raw.get("price"))
    if not item_id or name is None or price is None or price <= 0:
        return None
    flt = raw.get("float")
    seed = raw.get("paint_seed")
    inspect = raw.get("inspect_url")
    return CatalogueItem(
        id=item_id,
        name=name,
        price_usd=price,
        image_url=_str(raw.get("image_url")),
        phase=_str(raw.get("phase")),
        float_value=float(flt)
        if isinstance(flt, int | float) and not isinstance(flt, bool)
        else None,
        paint_seed=seed if isinstance(seed, int) and not isinstance(seed, bool) else None,
        inspect_url=inspect
        if isinstance(inspect, str) and inspect.startswith("steam://")
        else None,
    )


# Any: Skinslink's purchase object, read field by field.
def _purchase(raw: object) -> Purchase:
    """A purchase answer; an answer without an integer id is an outage, not a purchase."""
    if not isinstance(raw, Mapping):
        raise SkinslinkUnavailableError("unexpected body")
    pid = raw.get("id")
    status = _str(raw.get("status"))
    if not isinstance(pid, int) or isinstance(pid, bool) or status is None:
        raise SkinslinkUnavailableError("unexpected body")
    item = raw.get("item")
    item_id = item.get("id") if isinstance(item, Mapping) else None
    asset = raw.get("asset_id", item_id)
    return Purchase(
        id=pid,
        merchant_tx_id=_str(raw.get("merchant_tx_id")),
        status=status,
        offer_id=_str(raw.get("trade_offer_id")) or _str(raw.get("offer_id")),
        fail_reason=_str(raw.get("fail_reason")),
        amount_usd=_decimal(raw.get("amount")),
        asset_id=str(asset)
        if isinstance(asset, int | str) and not isinstance(asset, bool)
        else None,
        hold_end_date=_str(raw.get("hold_end_date")),
    )


# Any: an error body's ``data`` (a list of field errors, or an object).
def _code(body: Mapping[str, Any]) -> str | None:
    """The domain code of a refusal: the first field error's ``code``, or a ``fail_reason``."""
    data = body.get("data")
    if isinstance(data, list):
        for entry in data:
            if isinstance(entry, Mapping) and isinstance(entry.get("code"), str):
                return str(entry["code"])
    if isinstance(data, Mapping):
        return _str(data.get("fail_reason"))
    return None


class _PageRebuildingError(Exception):
    """A catalogue page is being rebuilt: ask again after ``seconds``."""

    def __init__(self, seconds: int) -> None:
        super().__init__(f"retry after {seconds} s")
        self.seconds = seconds


def _loads(text: str) -> object:
    try:
        return json.loads(text)
    except ValueError:
        return None


def _json_or_none(resp: httpx.Response) -> object:
    try:
        return resp.json()
    except ValueError:
        return None


class SkinslinkClient:
    """Async Skinslink merchant client; inject ``client`` in tests."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        timeout_seconds: float,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._client = client

    @asynccontextmanager
    async def _session(self) -> AsyncIterator[httpx.AsyncClient]:
        if self._client is not None:
            yield self._client
            return
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            yield client

    async def _request(
        self,
        method: str,
        path: str,
        *,
        endpoint: SkinslinkEndpoint,
        params: Mapping[str, str] | None = None,
        json_body: Mapping[str, object] | None = None,
    ) -> Any:  # Any: Skinslink's ``data``, narrowed by each caller
        """``{method} {base_url}{path}`` → ``data``; every failure as a typed error."""
        if not self._api_key:
            raise SkinslinkUnavailableError("no api key")
        try:
            async with self._session() as client:
                resp = await client.request(
                    method,
                    f"{self._base_url}{path}",
                    params=params,
                    json=json_body,
                    headers={"X-Api-Key": self._api_key},
                )
        except httpx.HTTPError as exc:
            record_skinslink_call(endpoint, "unavailable")
            raise SkinslinkUnavailableError(type(exc).__name__) from exc
        return self._verdict(resp.status_code, _json_or_none(resp), endpoint)

    # Any: Skinslink's ``data``, narrowed by each caller.
    def _verdict(self, status: int, body: object, endpoint: SkinslinkEndpoint) -> Any:
        """``data`` of a success; every other answer as a typed error."""
        if status == 429:
            record_skinslink_call(endpoint, "rate_limited")
            raise SkinslinkRateLimitedError("rate limited")
        if status == 403:
            record_skinslink_call(endpoint, "forbidden")
            raise SkinslinkForbiddenError("forbidden", status=403)
        if status in _RETRYABLE:
            record_skinslink_call(endpoint, "unavailable")
            raise SkinslinkUnavailableError(f"http {status}")
        if status == 404:
            record_skinslink_call(endpoint, "not_found")
            raise SkinslinkError("not found", status=404)
        if not isinstance(body, Mapping):
            record_skinslink_call(endpoint, "unavailable")
            raise SkinslinkUnavailableError("unexpected body")
        if status >= 400 or body.get("success") is not True:
            record_skinslink_call(endpoint, "refused")
            code = _code(body)
            log.info("skinslink.refused", endpoint=endpoint, status=status, code=code)
            raise SkinslinkError("refused", status=status, code=code)
        record_skinslink_call(endpoint, "ok")
        return body.get("data")

    async def available_batches(
        self,
        on_batch: Callable[[list[CatalogueItem]], Awaitable[None]],
        *,
        game: str = "csgo",
        batch_size: int = 1000,
    ) -> str:
        """``GET /merchant/purchase/available`` (full, extended), walked page by page (1..16,
        each a fixed slice keyed by id, so a walk never skips or repeats an item) and each
        page streamed: ``on_batch`` gets the readable items ``batch_size`` at a time; the
        list is never in memory whole. A page being rebuilt (503 + ``Retry-After``) is asked
        again after the wait.

        Returns:
            The oldest page's ``last_update_at``: events from there replay any change made
            during the walk (now, when Skinslink gave none).

        Raises:
            SkinslinkError: A refusal. SkinslinkForbiddenError: HTTP 403.
            SkinslinkUnavailableError: Transport, 5xx, 429, or a truncated or unreadable body.
        """
        if not self._api_key:
            raise SkinslinkUnavailableError("no api key")
        cursors: list[str] = []
        page, total = 1, 1
        while page <= total:
            scanner = await self._page(game, page, on_batch, batch_size)
            cursors.append(self._cursor_of(scanner))
            total = scanner.total_pages or 1  # an unpaginated answer is page 1 of 1
            page += 1
        return min(cursors)

    async def _page(
        self,
        game: str,
        page: int,
        on_batch: Callable[[list[CatalogueItem]], Awaitable[None]],
        batch_size: int,
    ) -> ItemsScanner:
        """One page, asked again while Skinslink says it is being rebuilt."""
        for _ in range(_PAGE_TRIES):
            scanner = ItemsScanner()
            try:
                await self._stream_page(game, page, scanner, on_batch, batch_size)
            except _PageRebuildingError as wait:
                await asyncio.sleep(min(wait.seconds, _MAX_PAGE_WAIT))
                continue
            return scanner
        record_skinslink_call("available", "unavailable")
        raise SkinslinkUnavailableError(f"page {page} kept being rebuilt")

    async def _stream_page(
        self,
        game: str,
        page: int,
        scanner: ItemsScanner,
        on_batch: Callable[[list[CatalogueItem]], Awaitable[None]],
        batch_size: int,
    ) -> None:
        params = {"game": game, "full": "true", "extended": "true", "page": str(page)}
        try:
            async with (
                self._session() as client,
                client.stream(
                    "GET",
                    f"{self._base_url}/merchant/purchase/available",
                    params=params,
                    headers={"X-Api-Key": self._api_key},
                ) as resp,
            ):
                if resp.status_code != 200:
                    await resp.aread()
                    retry_after = resp.headers.get("Retry-After", "")
                    if resp.status_code == 503 and retry_after.isdigit():
                        raise _PageRebuildingError(int(retry_after))
                    self._verdict(resp.status_code, _json_or_none(resp), "available")
                    raise SkinslinkUnavailableError(f"http {resp.status_code}")
                await self._scan(resp, scanner, on_batch, batch_size)
        except httpx.HTTPError as exc:
            record_skinslink_call("available", "unavailable")
            raise SkinslinkUnavailableError(type(exc).__name__) from exc

    async def _scan(
        self,
        resp: httpx.Response,
        scanner: ItemsScanner,
        on_batch: Callable[[list[CatalogueItem]], Awaitable[None]],
        batch_size: int,
    ) -> None:
        batch: list[CatalogueItem] = []
        async for text in resp.aiter_text():
            try:
                raws = scanner.feed(text)
            except ValueError as exc:
                record_skinslink_call("available", "unavailable")
                raise SkinslinkUnavailableError("unexpected body") from exc
            batch += [i for raw in raws if isinstance(raw, Mapping) and (i := _item(raw))]
            while len(batch) >= batch_size:
                await on_batch(batch[:batch_size])
                batch = batch[batch_size:]
        if scanner.headless is not None:  # an error answer, never an items array
            self._verdict(200, _loads(scanner.headless), "available")
            raise SkinslinkUnavailableError("unexpected body")
        if batch:
            await on_batch(batch)

    def _cursor_of(self, scanner: ItemsScanner) -> str:
        try:
            cursor = scanner.finish()
        except ValueError as exc:
            record_skinslink_call("available", "unavailable")
            raise SkinslinkUnavailableError("unexpected body") from exc
        record_skinslink_call("available", "ok")
        if cursor is None:
            log.warning("skinslink.available.no_cursor")
            cursor = datetime.now(UTC).isoformat()
        return cursor

    async def events(self, since: str, *, game: str = "csgo", limit: int = 10000) -> EventsPage:
        """``GET /merchant/purchase/events``: what changed after ``since``."""
        data = await self._request(
            "GET",
            "/merchant/purchase/events",
            endpoint="events",
            params={"since": since, "game": game, "extended": "true", "limit": str(limit)},
        )
        if not isinstance(data, Mapping) or not isinstance(data.get("events"), list):
            raise SkinslinkUnavailableError("unexpected body")
        nxt = _str(data.get("next"))
        if nxt is None:
            raise SkinslinkUnavailableError("unexpected body")
        events: list[CatalogueEvent] = []
        for raw in data["events"]:
            if not isinstance(raw, Mapping):
                continue
            kind, item_id = raw.get("type"), raw.get("id")
            if kind not in ("upsert", "remove") or not isinstance(item_id, int | str):
                continue
            card = _item(raw["item"]) if isinstance(raw.get("item"), Mapping) else None
            if kind == "upsert" and card is None:
                continue
            events.append(
                CatalogueEvent(type=kind, at=str(raw.get("at", "")), id=str(item_id), item=card)
            )
        return EventsPage(
            since=str(data.get("since", since)),
            next=nxt,
            more=data.get("more") is True,
            reset=data.get("reset") is True,
            events=events,
        )

    async def purchase(
        self,
        *,
        asset_id: str,
        partner: int,
        token: str,
        merchant_tx_id: str,
        max_price_usd: Decimal,
    ) -> Purchase:
        """``POST /merchant/purchase``: idempotent on ``merchant_tx_id`` (a repeat returns
        the stored purchase, never a second one); never above ``max_price_usd``.

        Raises:
            SkinslinkError: A refusal (``code`` set for a validation error; 409 duplicate).
            SkinslinkForbiddenError: HTTP 403.
            SkinslinkRateLimitedError: HTTP 429.
            SkinslinkUnavailableError: The purchase may exist: resolve by repeating.
        """
        data = await self._request(
            "POST",
            "/merchant/purchase",
            endpoint="purchase",
            json_body={
                "game": "csgo",
                "asset_id": asset_id,
                "partner": partner,
                "token": token,
                "merchant_tx_id": merchant_tx_id,
                # Skinslink prices to 1/1000 $; rounded down, the cap is never above our cost.
                "max_price": float(max_price_usd.quantize(_THREE_PLACES, rounding=ROUND_DOWN)),
            },
        )
        return _purchase(data)

    async def purchase_status(self, *, merchant_tx_id: str) -> Purchase | None:
        """``GET /merchant/purchase/status``; ``None`` when Skinslink has no such purchase."""
        try:
            data = await self._request(
                "GET",
                "/merchant/purchase/status",
                endpoint="status",
                params={"merchant_tx_id": merchant_tx_id},
            )
        except SkinslinkError as exc:
            if exc.status == 404:
                return None
            raise
        return _purchase(data)

    async def balance(self) -> Balance:
        """``GET /merchant/balance`` (USD)."""
        data = await self._request("GET", "/merchant/balance", endpoint="balance")
        if not isinstance(data, Mapping):
            raise SkinslinkUnavailableError("unexpected body")
        total, hold, available = (_decimal(data.get(k)) for k in ("total", "hold", "available"))
        if total is None or hold is None or available is None:
            raise SkinslinkUnavailableError("unexpected body")
        return Balance(total=total, hold=hold, available=available)


def client_for(settings: Settings, *, timeout_seconds: float | None = None) -> SkinslinkClient:
    """The process's Skinslink client (catalogue timeout unless ``timeout_seconds``)."""
    return SkinslinkClient(
        api_key=settings.skinslink_api_key,
        base_url=settings.skinslink_base_url,
        timeout_seconds=timeout_seconds or settings.skinslink_request_timeout_seconds,
    )


__all__ = [
    "LINK_ERROR_CODES",
    "PURCHASE_FAIL_REASONS",
    "AvailablePage",
    "Balance",
    "CatalogueEvent",
    "CatalogueItem",
    "EventsPage",
    "Purchase",
    "SkinslinkClient",
    "SkinslinkError",
    "SkinslinkForbiddenError",
    "SkinslinkPurchaseClient",
    "SkinslinkRateLimitedError",
    "SkinslinkUnavailableError",
    "client_for",
]
