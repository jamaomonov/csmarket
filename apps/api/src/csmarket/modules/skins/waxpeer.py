"""Waxpeer HTTP client — transport only.

Four reads: ``check-tradelink``, the CSV price snapshot, item prices and live
search-by-name; buying arrives in M4. Two facts shape it: refusals arrive as HTTP 200
with ``success: false``, and the API key travels as the ``api`` query parameter — so the
URL is never logged (``httpx`` loggers are capped at WARNING in ``core.logging``), only
method + path + status.
"""

from __future__ import annotations

import contextlib
import csv
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import httpx

from csmarket.core.logging import get_logger

log = get_logger("csmarket.skins.waxpeer")


class WaxpeerError(Exception):
    """Waxpeer refused the call (transport ok, business failure)."""

    def __init__(self, message: str, *, status: int = 200, body: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.body = body


class WaxpeerUnavailableError(Exception):
    """Waxpeer could not be reached, gave an unreadable answer, or no API key is configured."""


class WaxpeerRateLimitedError(WaxpeerUnavailableError):
    """HTTP 429. A rate limit is an outage to callers that do not care which.

    Attributes:
        retry_after_seconds: Waxpeer's own hint (``Retry-After`` or ``msBeforeNext``).
    """

    def __init__(self, message: str, *, retry_after_seconds: float | None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


@dataclass(frozen=True)
class SnapshotRow:
    """One listing from the CSV snapshot. ``auto`` is Waxpeer's instant-delivery flag."""

    item_id: int
    name: str
    price_units: int
    auto: bool


#: Columns the snapshot parser reads by name; any missing one fails the tick.
_SNAPSHOT_COLUMNS = frozenset({"item_id", "name", "price", "auto"})
_SNAPSHOT_PATH = "/v1/prices/snapshot"
_SNAPSHOT_READ_TIMEOUT = 300.0
_PRICES_TIMEOUT = 120.0
_SEARCH_MAX_NAMES = 50


def _retry_after(headers: Mapping[str, str], body: object) -> float | None:
    """Waxpeer's retry hint in seconds: ``Retry-After`` header, else body ``msBeforeNext``."""
    raw = headers.get("Retry-After")
    if raw:
        try:
            return float(raw)
        except ValueError:
            return None
    if isinstance(body, dict):
        wait = body.get("msBeforeNext")
        if isinstance(wait, int | float) and not isinstance(wait, bool):
            return float(wait) / 1000
    return None


def _snapshot_row(header: Sequence[str], cells: Sequence[str]) -> SnapshotRow | None:
    """One snapshot line, or ``None`` when its id, price or name is unknown.

    An empty cell or a zero price is unknown, and so is a cell a short line (a truncated
    last line) does not reach.
    """
    row = dict(zip(header, cells, strict=False))
    try:
        price = int(row["price"]) if row["price"] else 0
        item_id = int(row["item_id"])
        name = row["name"]
    except (KeyError, ValueError):
        return None
    if price <= 0:
        # Waxpeer writes an unknown value as an empty cell; a listing priced 0 would sell a
        # knife at the floor.
        return None
    return SnapshotRow(
        item_id=item_id, name=name, price_units=price, auto=row.get("auto") == "true"
    )


class WaxpeerClient:
    """Async Waxpeer client; inject ``client`` in tests."""

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
        self._host = self._base_url.removesuffix("/v1")
        self._timeout = timeout_seconds
        self._client = client

    @contextlib.asynccontextmanager
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
        json: dict[str, Any] | None = None,  # Any: JSON request body of mixed value types
    ) -> dict[str, Any]:  # Any: Waxpeer's JSON body, narrowed by each caller
        self._require_key()
        try:
            async with self._session() as client:
                resp = await client.request(
                    method, f"{self._base_url}{path}", params={"api": self._api_key}, json=json
                )
        except httpx.HTTPError as exc:
            log.warning("waxpeer.network_error", method=method, path=path, error=type(exc).__name__)
            raise WaxpeerUnavailableError(type(exc).__name__) from exc
        log.info("waxpeer.request", method=method, path=path, status=resp.status_code)
        if resp.status_code >= 400:
            raise WaxpeerError(resp.text[:200], status=resp.status_code, body=resp.text)
        # A 200 we cannot read is an upstream fault, not a refusal: as a ``WaxpeerError``
        # it would reach callers as Waxpeer's reason text (ruling P10).
        try:
            body = resp.json()
        except ValueError as exc:
            log.warning("waxpeer.unexpected_body", method=method, path=path)
            raise WaxpeerUnavailableError("unexpected body") from exc
        if not isinstance(body, dict):
            log.warning("waxpeer.unexpected_body", method=method, path=path)
            raise WaxpeerUnavailableError("unexpected body")
        if not body.get("success", False):
            raise WaxpeerError(str(body.get("msg") or "refused"), body=resp.text)
        return body

    def _require_key(self) -> None:
        if not self._api_key:
            raise WaxpeerUnavailableError("waxpeer api key is not configured")

    async def _get_json(
        self,
        path: str,
        params: list[tuple[str, str]],
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:  # Any: Waxpeer's JSON body, narrowed by each caller
        """``GET {host}{path}``; the key is added here and never logged.

        ``path`` is relative to the host (``/v1/prices``), so one helper serves v1 and v2.
        """
        self._require_key()
        try:
            async with self._session() as client:
                resp = await client.get(
                    f"{self._host}{path}",
                    params=[("api", self._api_key), *params],
                    timeout=timeout if timeout is not None else httpx.USE_CLIENT_DEFAULT,
                )
        except httpx.HTTPError as exc:
            log.warning("waxpeer.network_error", method="GET", path=path, error=type(exc).__name__)
            raise WaxpeerUnavailableError(type(exc).__name__) from exc
        log.info("waxpeer.request", method="GET", path=path, status=resp.status_code)
        try:
            body: object = resp.json()
        except ValueError:
            body = None
        if resp.status_code == 429:
            raise WaxpeerRateLimitedError(
                "rate limited", retry_after_seconds=_retry_after(resp.headers, body)
            )
        if resp.status_code >= 400:
            raise WaxpeerError(resp.text[:200], status=resp.status_code, body=resp.text)
        if not isinstance(body, dict):
            log.warning("waxpeer.unexpected_body", method="GET", path=path)
            raise WaxpeerUnavailableError("unexpected body")
        return body

    async def iter_snapshot_rows(self, *, game: str = "csgo") -> AsyncIterator[SnapshotRow]:
        """Stream ``GET /v1/prices/snapshot?format=csv`` one listing at a time.

        The body is ~240 MB of text for CS2; it is consumed through ``aiter_lines`` and
        never held whole. Columns are read by name from the header, so a reordering
        upstream fails loudly rather than silently swapping ``price`` and ``item_id``.
        Rows with an unknown or zero price are skipped and counted.

        Raises:
            WaxpeerUnavailableError: No API key, or the network failed.
            WaxpeerRateLimitedError: Waxpeer answered 429.
            WaxpeerError: An HTTP error status, or the header lacks a required column.
        """
        self._require_key()
        params = {"api": self._api_key, "format": "csv", "game": game}
        timeout = httpx.Timeout(self._timeout, read=_SNAPSHOT_READ_TIMEOUT)
        rows = bad_rows = 0
        try:
            async with (
                self._session() as client,
                client.stream(
                    "GET", f"{self._host}{_SNAPSHOT_PATH}", params=params, timeout=timeout
                ) as resp,
            ):
                log.info(
                    "waxpeer.request", method="GET", path=_SNAPSHOT_PATH, status=resp.status_code
                )
                if resp.status_code == 429:
                    raise WaxpeerRateLimitedError(
                        "rate limited", retry_after_seconds=_retry_after(resp.headers, None)
                    )
                if resp.status_code >= 400:
                    await resp.aread()
                    raise WaxpeerError(resp.text[:200], status=resp.status_code, body=resp.text)
                header: list[str] | None = None
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    cells = next(csv.reader([line]))
                    if header is None:
                        header = cells
                        missing = _SNAPSHOT_COLUMNS.difference(header)
                        if missing:
                            # Once, loudly — not 1.19 M bad-row warnings per tick.
                            raise WaxpeerError(f"snapshot columns missing: {sorted(missing)}")
                        continue
                    row = _snapshot_row(header, cells)
                    if row is None:
                        bad_rows += 1
                        continue
                    rows += 1
                    yield row
                if header is None:
                    # An empty or truncated 200 is an outage: a sync that trusts "finished"
                    # would otherwise deactivate the whole catalogue.
                    log.warning("waxpeer.unexpected_body", method="GET", path=_SNAPSHOT_PATH)
                    raise WaxpeerUnavailableError("unexpected body")
        except httpx.HTTPError as exc:
            log.warning(
                "waxpeer.network_error", method="GET", path=_SNAPSHOT_PATH, error=type(exc).__name__
            )
            raise WaxpeerUnavailableError(type(exc).__name__) from exc
        log.info("waxpeer.snapshot.done", rows=rows, bad_rows=bad_rows)

    async def prices(self, *, game: str = "csgo") -> list[dict[str, Any]]:
        """``GET /v1/prices?minified=0`` — one row per Waxpeer name with image, type, rarity.

        Raises:
            WaxpeerUnavailableError: No API key, the network failed, or an unreadable 200.
            WaxpeerRateLimitedError: Waxpeer answered 429.
            WaxpeerError: An HTTP error status.
        """
        body = await self._get_json(
            "/v1/prices", [("game", game), ("minified", "0")], timeout=_PRICES_TIMEOUT
        )
        items = body.get("items")
        return items if isinstance(items, list) else []

    async def search_listings(
        self, names: Sequence[str], *, game: str = "csgo"
    ) -> dict[str, list[dict[str, Any]]]:
        """``GET /v2/search-items-by-name`` with ``delivery_details=1`` (at most 50 names).

        Returns Waxpeer's ``items`` map (name -> listings). Hold listings are never
        requested. Waxpeer allows 20 calls a minute: a 429 raises
        :class:`WaxpeerRateLimitedError` with ``msBeforeNext`` as the hint.

        Raises:
            WaxpeerUnavailableError: No API key, the network failed, or an unreadable 200
                (an HTML challenge page, a body that is not a JSON object).
            WaxpeerRateLimitedError: Waxpeer answered 429.
            WaxpeerError: An HTTP error status.
        """
        body = await self._get_json(
            "/v2/search-items-by-name",
            [
                ("game", game),
                ("minified", "0"),
                ("delivery_details", "1"),
                *[("name", name) for name in names[:_SEARCH_MAX_NAMES]],
            ],
        )
        items = body.get("items")
        return items if isinstance(items, dict) else {}

    async def check_tradelink(self, url: str) -> str | None:
        """``POST /v1/check-tradelink``: ``None`` when the link works, else Steam's reason.

        ``success: true`` with ``info`` (private inventory, trade ban) and ``success: false``
        with ``msg`` (a link Waxpeer won't use) both come back as reason text; a transport
        failure or HTTP error raises.

        Raises:
            WaxpeerUnavailableError: No API key, the network failed, or a 200 whose body
                is not a JSON object.
            WaxpeerError: Waxpeer answered with an HTTP error status.
        """
        try:
            body = await self._request("POST", "/check-tradelink", json={"tradelink": url})
        except WaxpeerError as exc:
            if exc.status == 200:
                return str(exc) or "refused"
            raise
        info = body.get("info")
        return str(info) if info else None


__all__ = [
    "SnapshotRow",
    "WaxpeerClient",
    "WaxpeerError",
    "WaxpeerRateLimitedError",
    "WaxpeerUnavailableError",
]
