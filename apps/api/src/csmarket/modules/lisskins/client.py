"""LIS-SKINS API client (OpenAPI of https://lis-skins.stoplight.io, read 2026-10-07).

``Authorization: Bearer <key>`` on every call; answers are ``{"data": …}``, refusals
``{"error": "<code>"}`` (400 / 422). Error bodies are never logged, and a purchase's
``steam_id`` (the buyer's) is never read. Amounts are USD as ``Decimal`` built from the JSON
number's text. Rate limits: 200 requests/min, ``market/buy`` 500/min; 429 + ``Retry-After``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from typing import Any, Protocol

import httpx

from csmarket.core.config import Settings, get_settings
from csmarket.core.logging import get_logger
from csmarket.core.metrics import LisskinsEndpoint, record_lisskins_call
from csmarket.modules.lisskins.values import decimal_of, int_of, str_of

log = get_logger("csmarket.lisskins.client")

#: ``POST /market/buy`` refusals that name the buyer's trade link or account: any other lot
#: would be refused the same way, so the order is refunded ``invalid_trade_link``. The two
#: ``invalid_*_value`` codes are the 422 spelling of a malformed link.
BUY_LINK_ERRORS = frozenset(
    {
        "invalid_trade_url",
        "user_trade_ban",
        "user_cant_trade",
        "private_inventory",
        "too_many_failed_attempts_for_user",
        "invalid_partner_value",
        "invalid_token_value",
    }
)
#: A returned skin's ``error`` that is the buyer's side (``return_reason=trade_create_error``).
TRADE_LINK_ERRORS = frozenset(
    {
        "invalid_trade_url",
        "user_cant_trade",
        "private_inventory",
        "user_trade_ban",
        "user_inventory_full",
    }
)
#: ``GET /market/info`` takes at most this many ids per call.
INFO_MAX_IDS = 200
_CENTS = Decimal("0.01")
_RETRYABLE = frozenset({408, 500, 502, 503, 504})


class LisskinsError(Exception):
    """LIS-SKINS answered and said no: a 4xx other than 401 / 403 / 429."""

    def __init__(
        self,
        message: str,
        *,
        status: int,
        code: str | None = None,
        unavailable_ids: tuple[int, ...] = (),
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.unavailable_ids = unavailable_ids


class LisskinsForbiddenError(LisskinsError):
    """401 / 403: the key is wrong or revoked, or this host may not use it; also no key at
    all (``code="no_api_key"``), raised before any call."""


class LisskinsUnavailableError(Exception):
    """No answer worth reading: transport, 408/5xx, or an unreadable body."""


class LisskinsRateLimitedError(LisskinsUnavailableError):
    """429; ``retry_after`` is the wait it asked for, in seconds."""

    def __init__(self, message: str, *, retry_after: float | None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


@dataclass(frozen=True)
class PurchasedSkin:
    """One skin of a purchase, as LIS-SKINS reports it."""

    id: int
    price_usd: Decimal | None
    #: ``processing``, ``wait_accept``, ``accepted``, ``return``, ``wait_unlock``,
    #: ``wait_withdraw``.
    status: str
    return_reason: str | None
    error: str | None
    #: Steam's trade offer id.
    offer_id: str | None
    offer_expiry_at: str | None


@dataclass(frozen=True)
class Purchase:
    """A purchase (``market/buy`` / ``market/info``); never the buyer's Steam id."""

    purchase_id: int
    custom_id: str | None
    skins: tuple[PurchasedSkin, ...]

    @property
    def skin(self) -> PurchasedSkin:
        """The one skin we buy per purchase."""
        return self.skins[0]


@dataclass(frozen=True)
class Balance:
    """Our LIS-SKINS balance, USD."""

    available: Decimal
    locked: Decimal
    protected: Decimal


@dataclass(frozen=True)
class Availability:
    """``check-availability``: live prices of the lots still for sale, and the gone ones."""

    available: dict[int, Decimal]
    unavailable: frozenset[int]


class LisskinsBuyClient(Protocol):
    """What the order worker and the reconcile need from LIS-SKINS."""

    async def buy(
        self, *, skin_id: int, partner: int, token: str, max_price_usd: Decimal, custom_id: str
    ) -> Purchase:
        """Buy lot ``skin_id`` for the trade link ``partner``/``token``."""
        ...

    async def info(self, *, custom_ids: Sequence[str]) -> list[Purchase]:
        """The purchases under ``custom_ids`` (≤ :data:`INFO_MAX_IDS`)."""
        ...


class AvailabilityClient(Protocol):
    """What checkout needs from LIS-SKINS."""

    async def check_availability(self, ids: Sequence[int]) -> Availability:
        """Live prices of ``ids``."""
        ...


def _ints(value: object) -> tuple[int, ...]:
    items = value if isinstance(value, list) else []
    return tuple(n for v in items if (n := int_of(v)) is not None)


# Any: one JSON object of LIS-SKINS', read field by field.
def _skin(raw: Mapping[str, Any]) -> PurchasedSkin | None:
    skin_id, status = int_of(raw.get("id")), str_of(raw.get("status"))
    if skin_id is None or status is None:
        return None
    return PurchasedSkin(
        id=skin_id,
        price_usd=decimal_of(raw.get("price")),
        status=status,
        return_reason=str_of(raw.get("return_reason")),
        error=str_of(raw.get("error")),
        offer_id=str_of(raw.get("steam_trade_offer_id")),
        offer_expiry_at=str_of(raw.get("steam_trade_offer_expiry_at")),
    )


def _purchase(raw: object) -> Purchase:
    """A purchase answer; one without an id or a readable skin is an outage."""
    if not isinstance(raw, Mapping):
        raise LisskinsUnavailableError("unexpected body")
    pid = int_of(raw.get("purchase_id"))
    listed = raw.get("skins")
    skins = tuple(
        s
        for item in (listed if isinstance(listed, list) else [])
        if isinstance(item, Mapping) and (s := _skin(item)) is not None
    )
    if pid is None or not skins:
        raise LisskinsUnavailableError("unexpected body")
    return Purchase(purchase_id=pid, custom_id=str_of(raw.get("custom_id")), skins=skins)


def _json_or_none(resp: httpx.Response) -> object:
    try:
        return resp.json()
    except ValueError:
        return None


def _retry_after(resp: httpx.Response) -> float | None:
    value = resp.headers.get("Retry-After", "")
    return float(value) if value.isdigit() else None


class LisskinsClient:
    """Async LIS-SKINS client; inject ``client`` in tests."""

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
        endpoint: LisskinsEndpoint,
        params: Sequence[tuple[str, str]] | None = None,
        json_body: Mapping[str, object] | None = None,
    ) -> Any:  # Any: LIS-SKINS' ``data``, narrowed by each caller
        """``{method} {base_url}{path}`` → ``data``; every failure as a typed error."""
        if not self._api_key:  # as a revoked key: a buy waits under ``source_forbidden``
            raise LisskinsForbiddenError("no api key", status=401, code="no_api_key")
        try:
            async with self._session() as client:
                resp = await client.request(
                    method,
                    f"{self._base_url}{path}",
                    params=list(params or ()),
                    json=json_body,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Accept": "application/json",
                    },
                )
        except httpx.HTTPError as exc:
            record_lisskins_call(endpoint, "unavailable")
            raise LisskinsUnavailableError(type(exc).__name__) from exc
        return self._verdict(resp, endpoint)

    def _verdict(self, resp: httpx.Response, endpoint: LisskinsEndpoint) -> Any:  # Any: as above
        status, body = resp.status_code, _json_or_none(resp)
        if status == 429:
            record_lisskins_call(endpoint, "rate_limited")
            raise LisskinsRateLimitedError("rate limited", retry_after=_retry_after(resp))
        if status in (401, 403):
            record_lisskins_call(endpoint, "forbidden")
            raise LisskinsForbiddenError("forbidden", status=status)
        if status in _RETRYABLE or status >= 500:
            record_lisskins_call(endpoint, "unavailable")
            raise LisskinsUnavailableError(f"http {status}")
        if status >= 400:
            fields = body if isinstance(body, Mapping) else {}
            code = str_of(fields.get("error"))
            record_lisskins_call(endpoint, "refused")
            log.info("lisskins.refused", endpoint=endpoint, status=status, code=code)
            raise LisskinsError(
                "refused",
                status=status,
                code=code,
                unavailable_ids=_ints(fields.get("unavailable_ids")),
            )
        if not isinstance(body, Mapping) or "data" not in body:
            record_lisskins_call(endpoint, "unavailable")
            raise LisskinsUnavailableError("unexpected body")
        record_lisskins_call(endpoint, "ok")
        return body["data"]

    async def buy(
        self, *, skin_id: int, partner: int, token: str, max_price_usd: Decimal, custom_id: str
    ) -> Purchase:
        """``POST /market/buy`` for one lot; LIS-SKINS refuses a ``custom_id`` it knows
        (``custom_id_already_exists``), so a repeat never buys twice.

        Raises:
            LisskinsError: A refusal (``code`` names it). LisskinsForbiddenError: 401 / 403.
            LisskinsRateLimitedError: 429.
            LisskinsUnavailableError: The purchase may exist: resolve by ``info``.
        """
        data = await self._request(
            "POST",
            "/market/buy",
            endpoint="buy",
            json_body={
                "ids": [skin_id],
                "partner": str(partner),
                "token": token,
                # LIS-SKINS prices in cents; rounded down, the cap is never above our cost.
                "max_price": float(max_price_usd.quantize(_CENTS, rounding=ROUND_DOWN)),
                "custom_id": custom_id,
            },
        )
        return _purchase(data)

    async def info(self, *, custom_ids: Sequence[str]) -> list[Purchase]:
        """``GET /market/info`` by our ``custom_id``s; an unreadable entry is skipped.

        Raises:
            ValueError: More than :data:`INFO_MAX_IDS` ids (a caller bug).
        """
        if len(custom_ids) > INFO_MAX_IDS:
            raise ValueError(f"at most {INFO_MAX_IDS} custom ids per call")
        if not custom_ids:
            return []
        data = await self._request(
            "GET",
            "/market/info",
            endpoint="info",
            params=[("custom_ids[]", c) for c in custom_ids],
        )
        if not isinstance(data, list):
            raise LisskinsUnavailableError("unexpected body")
        found: list[Purchase] = []
        for raw in data:
            try:
                found.append(_purchase(raw))
            except LisskinsUnavailableError:
                continue
        return found

    async def check_availability(self, ids: Sequence[int]) -> Availability:
        """``GET /market/check-availability``; ``available_skins`` may come as ``[]``."""
        data = await self._request(
            "GET",
            "/market/check-availability",
            endpoint="check",
            params=[("ids[]", str(i)) for i in ids],
        )
        if not isinstance(data, Mapping):
            raise LisskinsUnavailableError("unexpected body")
        listed = data.get("available_skins")
        available = {
            skin_id: price
            for key, value in (listed.items() if isinstance(listed, Mapping) else ())
            if (skin_id := int_of(key)) is not None
            and (price := decimal_of(value)) is not None
            and price > 0
        }
        return Availability(
            available=available, unavailable=frozenset(_ints(data.get("unavailable_skin_ids")))
        )

    async def balance(self) -> Balance:
        """``GET /user/balance`` (USD)."""
        data = await self._request("GET", "/user/balance", endpoint="balance")
        available = decimal_of(data.get("balance")) if isinstance(data, Mapping) else None
        if available is None:
            raise LisskinsUnavailableError("unexpected body")
        return Balance(
            available=available,
            locked=decimal_of(data.get("balance_locked")) or Decimal(0),
            protected=decimal_of(data.get("trade_protection_balance")) or Decimal(0),
        )


def client_for(settings: Settings, *, timeout_seconds: float | None = None) -> LisskinsClient:
    """The process's LIS-SKINS client (the request timeout unless ``timeout_seconds``)."""
    return LisskinsClient(
        api_key=settings.lisskins_api_key,
        base_url=settings.lisskins_base_url,
        timeout_seconds=timeout_seconds or settings.lisskins_request_timeout_seconds,
    )


def availability_client() -> AvailabilityClient:
    """Checkout's client (the 4 s check timeout); tests override this dependency."""
    settings = get_settings()
    return client_for(settings, timeout_seconds=settings.lisskins_check_timeout_seconds)


def request_info_client() -> LisskinsClient:
    """The admin refund's LIS-SKINS client for one ``market/info`` lookup (ADR-0018; the 4 s
    check timeout; a FastAPI dependency, tests override it)."""
    settings = get_settings()
    return client_for(settings, timeout_seconds=settings.lisskins_check_timeout_seconds)


__all__ = [
    "BUY_LINK_ERRORS",
    "INFO_MAX_IDS",
    "TRADE_LINK_ERRORS",
    "Availability",
    "AvailabilityClient",
    "Balance",
    "LisskinsBuyClient",
    "LisskinsClient",
    "LisskinsError",
    "LisskinsForbiddenError",
    "LisskinsRateLimitedError",
    "LisskinsUnavailableError",
    "Purchase",
    "PurchasedSkin",
    "availability_client",
    "client_for",
    "request_info_client",
]
