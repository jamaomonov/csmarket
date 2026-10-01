"""Waxpeer HTTP client — transport only.

M1 needs one call (``check-tradelink``); M2 adds search, snapshot and buying. Two facts
shape it: refusals arrive as HTTP 200 with ``success: false``, and the API key travels as
the ``api`` query parameter — so the URL is never logged (``httpx`` loggers are capped at
WARNING in ``core.logging``), only method + path + status.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
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
        if not self._api_key:
            raise WaxpeerUnavailableError("waxpeer api key is not configured")
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


__all__ = ["WaxpeerClient", "WaxpeerError", "WaxpeerUnavailableError"]
