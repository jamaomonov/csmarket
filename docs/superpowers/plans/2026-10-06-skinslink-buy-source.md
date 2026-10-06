# Skinslink as a Second Buy Source — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show Skinslink's CS2 offers beside Waxpeer's, price the catalogue from the cheaper source, and buy from Skinslink when the buyer picks one of its offers — with the same money guards as the Waxpeer path.

**Architecture:** A new module `modules/skinslink/` owns the HTTP client, a mirror of Skinslink's stock (`skinslink_items`, kept current by a 15-second events poll), the purchase record (`skinslink_purchases`), the webhook (signature → a queued check, never trusted for status) and the balance read. `skins` gains a source-neutral `Offer` (`wx:<id>` / `sl:<id>`) and a per-item roll-up of Skinslink's cheapest price; `orders` routes the buy by `orders.source` to today's Waxpeer path (untouched) or to the new `skinslink_buying`, and applies Skinslink statuses to orders in `skinslink_status`. Everything is behind `CSMARKET_SKINSLINK_ENABLED`.

**Tech Stack:** FastAPI, SQLAlchemy 2 async, Alembic, Pydantic v2, httpx + respx, APScheduler, Postgres queue (`FOR UPDATE SKIP LOCKED` + `NOTIFY`), Next.js storefront (`@csmarket/utils` types), Vite admin.

**Spec:** `docs/superpowers/specs/2026-10-06-skinslink-buy-source-design.md`

## Global Constraints

- The word `supplier` is banned in `apps/*/src` (`scripts/check-no-yupay.sh`): say **source** (`waxpeer` | `skinslink`).
- Never log PII: no `steam_id`, `partner`, `token`, trade link; Skinslink error bodies are never logged (type name only). `skinslink_api_key` and `skinslink_secret` join the log redaction list.
- No new synchronous external call on the request path: offers come from the mirror; the webhook only verifies and enqueues.
- Money paths have tests for success, retryable failure and idempotent re-call; `skinslink`, `orders`, `skins` ≥ 95 % line coverage (`scripts/check-module-coverage.py`).
- The customer never sees a source name; `degraded` keeps meaning "Waxpeer answered from a fallback".
- Units: Waxpeer units (1000 = $1) stay the catalogue's cost unit; Skinslink USD × 1000, rounded half up to an int.
- Offer id on the wire: `wx:<int>` or `sl:<asset id>`; `POST /orders` accepts a bare JSON integer as `wx:` for one release.
- `CSMARKET_SKINSLINK_ENABLED=false` → nothing changes: no mirror ticks, no offers, no prices, webhook 404.
- Commits: Conventional Commits, scope `api/skinslink`, `api/skins`, `api/orders`, `scheduler`, `worker`, `web/skins`, `admin/orders`, `infra`, `docs`; trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` (or the session's model line).
- Run `make lint typecheck` and the task's tests before each commit; `make gen-api` whenever a route or schema changes, commit `docs/api/openapi.json` + `packages/api-client`.

## Review Focus

1. A Skinslink item whose `market_hash_name` has no row in `skin_items` (not in our catalogue, or a Doppler without `phase`) must never appear as an offer or move a price — pinned in Task 4 (`test_unmapped_items_are_kept_but_never_offered`).
2. A mirror older than 10 minutes must drop Skinslink from offers and from the cost used for prices, and must not deactivate a Waxpeer-only item — pinned in Task 4 and Task 6 (`test_stale_mirror_offers_nothing`, `test_stale_mirror_does_not_price`).
3. A webhook with a valid signature but a forged `status` must not move an order — pinned in Task 9 (`test_webhook_body_is_not_trusted`).
4. A `POST /merchant/purchase` that times out after Skinslink created the purchase must be resolved by repeating the same `merchant_tx_id`, never by a second buy and never by a silent refund — pinned in Task 8 (`test_lost_answer_is_resolved_by_repeat`).
5. An order whose Skinslink offer is gone must fall back to the cheapest offer of **either** source within the ceiling at checkout and at buy time, and otherwise refund `sold_out` — pinned in Task 7 (`test_next_offer_crosses_sources`) and Task 8 (`test_item_sold_substitutes_once_then_refunds`).

---

### Task 1: Settings, secrets, redaction, gates, module skeleton

**Files:**

- Modify: `apps/api/src/csmarket/core/config.py` (after `waxpeer_base_url`)
- Modify: `apps/api/src/csmarket/core/logging.py:60-70` (redaction list)
- Modify: `.env.example`, `infra/secrets-example/api.env`
- Modify: `scripts/check-module-coverage.py:24` (`MODULES`)
- Create: `apps/api/src/csmarket/modules/skinslink/__init__.py` (empty), `api.py`, `README.md`
- Test: `apps/api/tests/unit/test_skinslink_settings.py`

**Interfaces:**

- Produces: `Settings.skinslink_enabled: bool`, `skinslink_api_key: str`, `skinslink_secret: str`, `skinslink_base_url: str = "https://api.skinslink.com/api/v1"`, `skinslink_mirror_stale_minutes: int = 10`, `skinslink_request_timeout_seconds: float = 10.0`, `skinslink_buy_timeout_seconds: float = 35.0` (their purchase call blocks up to 30 s), `skinslink_balance_alert_usd: Decimal = 100`, and `Settings.skinslink_active -> bool` (enabled **and** both keys set).

- [ ] **Step 1: Write the failing test**

```python
# apps/api/tests/unit/test_skinslink_settings.py
"""Skinslink settings: off by default, active only with the switch and both keys."""

from __future__ import annotations

from csmarket.core.config import Settings


def test_disabled_by_default() -> None:
    s = Settings(_env_file=None)
    assert s.skinslink_enabled is False
    assert s.skinslink_active is False
    assert s.skinslink_base_url == "https://api.skinslink.com/api/v1"
    assert s.skinslink_mirror_stale_minutes == 10


def test_active_needs_switch_and_both_keys() -> None:
    assert Settings(_env_file=None, skinslink_enabled=True).skinslink_active is False
    assert (
        Settings(_env_file=None, skinslink_enabled=True, skinslink_api_key="k").skinslink_active
        is False
    )
    assert (
        Settings(
            _env_file=None, skinslink_enabled=True, skinslink_api_key="k", skinslink_secret="s"
        ).skinslink_active
        is True
    )
```

- [ ] **Step 2: Run it**

Run: `cd apps/api && uv run pytest tests/unit/test_skinslink_settings.py -q`
Expected: FAIL — `Settings` has no field `skinslink_enabled`.

- [ ] **Step 3: Add the settings**

In `core/config.py`, right after `waxpeer_base_url`:

```python
    # --- skinslink (second buy source; spec 2026-10-06) ---
    skinslink_enabled: bool = Field(
        default=False, description="Mirror Skinslink's stock, show its offers, buy from it."
    )
    skinslink_api_key: str = Field(default="", description="Skinslink merchant API key.")
    skinslink_secret: str = Field(
        default="", description="Skinslink merchant secret: signs its webhooks."
    )
    skinslink_base_url: str = Field(default="https://api.skinslink.com/api/v1")
    skinslink_mirror_stale_minutes: int = Field(
        default=10, ge=1, description="A mirror older than this offers and prices nothing."
    )
    skinslink_request_timeout_seconds: float = Field(default=10.0, gt=0)
    skinslink_buy_timeout_seconds: float = Field(
        default=35.0, gt=0, description="POST /merchant/purchase blocks up to 30 s on their side."
    )
    skinslink_balance_alert_usd: Decimal = Field(default=Decimal(100))

    @property
    def skinslink_active(self) -> bool:
        """Skinslink is used: switched on with both credentials present."""
        return self.skinslink_enabled and bool(self.skinslink_api_key and self.skinslink_secret)
```

(`Decimal` is already imported in `config.py`; check, else add `from decimal import Decimal`.)

In `core/logging.py` add to the redaction key list beside `"waxpeer_api_key"`: `"skinslink_api_key", "skinslink_secret",` and the header name `"x-api-key"`.

`.env.example` (after the Waxpeer block):

```
# Skinslink — the second buy source (spec 2026-10-06). Off until both keys are set.
CSMARKET_SKINSLINK_ENABLED=false
CSMARKET_SKINSLINK_API_KEY=
CSMARKET_SKINSLINK_SECRET=
```

`infra/secrets-example/api.env` (after `CSMARKET_WAXPEER_API_KEY`):

```
# Skinslink merchant credentials (docs/runbooks/skinslink.md). Rotate the pair the owner
# pasted in chat on 2026-10-06 before use. Webhook: https://api.csmarket.uz/api/v1/skinslink/webhook
CSMARKET_SKINSLINK_ENABLED=false
CSMARKET_SKINSLINK_API_KEY=CHANGE_ME_skinslink_api_key
CSMARKET_SKINSLINK_SECRET=CHANGE_ME_skinslink_secret
```

`scripts/check-module-coverage.py`: `MODULES = ("orders", "payments", "wallet", "skins", "notifications", "realtime", "skinslink")`.

`modules/skinslink/api.py`:

```python
"""Public interface of the ``skinslink`` module — other modules import from here only."""

from __future__ import annotations

__all__: list[str] = []
```

`modules/skinslink/README.md`: a heading, one paragraph (what it owns: the client, the mirror of Skinslink's stock, purchase records, the webhook, the balance read; what it does not: pricing, orders), a "Settings" table of the seven settings. Expanded in Task 12.

- [ ] **Step 4: Run the test and the gates**

Run: `cd apps/api && uv run pytest tests/unit/test_skinslink_settings.py -q && cd ../.. && make lint typecheck`
Expected: PASS; lint and mypy clean.

- [ ] **Step 5: Commit**

```bash
git add apps/api/src/csmarket/core/config.py apps/api/src/csmarket/core/logging.py .env.example infra/secrets-example/api.env scripts/check-module-coverage.py apps/api/src/csmarket/modules/skinslink apps/api/tests/unit/test_skinslink_settings.py
git commit -m "feat(api/skinslink): settings, redaction and the coverage gate for the second buy source"
```

---

### Task 2: The Skinslink HTTP client

**Files:**

- Create: `apps/api/src/csmarket/modules/skinslink/client.py`
- Modify: `apps/api/src/csmarket/modules/skinslink/api.py`
- Modify: `apps/api/src/csmarket/core/metrics.py` (one counter)
- Test: `apps/api/tests/contract/test_skinslink_client.py`

**Interfaces:**

- Produces (all in `client.py`, re-exported by `api.py`):
  - errors: `SkinslinkError(Exception)` with `.status: int` and `.code: str | None` (a validation `data[].code` or the top-level fail reason), `SkinslinkUnavailableError(Exception)` (transport, 408/5xx/502, unreadable body), `SkinslinkForbiddenError(SkinslinkError)` (403), `SkinslinkRateLimitedError(SkinslinkUnavailableError)` (429).
  - `@dataclass(frozen=True) CatalogueItem(id: str, name: str, price_usd: Decimal, image_url: str | None, phase: str | None, float_value: float | None, paint_seed: int | None, inspect_url: str | None)`
  - `@dataclass(frozen=True) CatalogueEvent(type: Literal["upsert","remove"], at: str, id: str, item: CatalogueItem | None)`
  - `@dataclass(frozen=True) EventsPage(since: str, next: str, more: bool, reset: bool, events: list[CatalogueEvent])`
  - `@dataclass(frozen=True) AvailablePage(items: list[CatalogueItem], last_update_at: str)`
  - `@dataclass(frozen=True) Purchase(id: int, merchant_tx_id: str | None, status: str, offer_id: str | None, fail_reason: str | None, amount_usd: Decimal | None, asset_id: str | None, hold_end_date: str | None)`
  - `@dataclass(frozen=True) Balance(total: Decimal, hold: Decimal, available: Decimal)`
  - `class SkinslinkClient` with `__init__(self, *, api_key: str, base_url: str, timeout_seconds: float, client: httpx.AsyncClient | None = None)` and: `available(game="csgo") -> AvailablePage`, `events(since: str, *, game="csgo", limit=10000) -> EventsPage`, `purchase(*, asset_id: str, partner: int, token: str, merchant_tx_id: str, max_price_usd: Decimal) -> Purchase`, `purchase_status(*, merchant_tx_id: str) -> Purchase | None` (404 → `None`), `balance() -> Balance`.
  - `PURCHASE_FAIL_REASONS = frozenset({...})` from the docs, `LINK_ERROR_CODES = frozenset({"trade_link_revoked","trade_link_invalid","trade_banned","profile_private","limited_account","hold","permissions","hold_and_permissions"})`.
  - `client_for(settings: Settings, *, timeout_seconds: float | None = None) -> SkinslinkClient`.
- Consumes: `Settings` fields from Task 1.

- [ ] **Step 1: Write the failing contract tests**

```python
# apps/api/tests/contract/test_skinslink_client.py
"""Skinslink merchant API (respx): catalogue, events, purchase, status, balance.

Shapes from https://docs.skinslink.com/llm (2026-10-06). Every partner, token and asset id
is made up.
"""

from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
import respx
from csmarket.modules.skinslink.api import (
    SkinslinkClient,
    SkinslinkError,
    SkinslinkForbiddenError,
    SkinslinkRateLimitedError,
    SkinslinkUnavailableError,
)

BASE = "https://api.skinslink.com/api/v1"


def _client() -> SkinslinkClient:
    return SkinslinkClient(api_key="k", base_url=BASE, timeout_seconds=1)


def _ok(data: object) -> dict[str, object]:
    return {"success": True, "message": "ok", "data": data}


ITEM = {
    "id": "38029384123",
    "name": "AK-47 | Redline (Field-Tested)",
    "price": 12.45,
    "image_url": "https://community.cloudflare.steamstatic.com/economy/image/x",
    "exterior": "Field-Tested",
    "float": 0.2512,
    "paint_seed": 661,
    "inspect_url": "steam://rungame/730/x",
    "phase": None,
}


@respx.mock
async def test_available_sends_the_key_header_and_parses_items() -> None:
    route = respx.get(f"{BASE}/merchant/purchase/available").mock(
        return_value=httpx.Response(
            200,
            json=_ok(
                {"game": "csgo", "total": 1, "items": [ITEM], "last_update_at": "2026-10-06T10:00:00Z"}
            ),
        )
    )
    page = await _client().available()
    assert route.calls.last.request.headers["X-Api-Key"] == "k"
    assert route.calls.last.request.url.params["full"] == "true"
    assert route.calls.last.request.url.params["extended"] == "true"
    assert page.last_update_at == "2026-10-06T10:00:00Z"
    item = page.items[0]
    assert (item.id, item.price_usd, item.float_value, item.paint_seed) == (
        "38029384123",
        Decimal("12.45"),
        0.2512,
        661,
    )


@respx.mock
async def test_events_keeps_the_cursor_verbatim_and_reads_upsert_and_remove() -> None:
    respx.get(f"{BASE}/merchant/purchase/events").mock(
        return_value=httpx.Response(
            200,
            json=_ok(
                {
                    "since": "2026-10-06T10:00:00Z",
                    "next": "2026-10-06T10:00:12.512434831Z",
                    "count": 2,
                    "more": True,
                    "reset": False,
                    "events": [
                        {"type": "upsert", "at": "2026-10-06T10:00:11Z", "game": "csgo", "id": ITEM["id"], "item": ITEM},
                        {"type": "remove", "at": "2026-10-06T10:00:12Z", "game": "csgo", "id": "1"},
                    ],
                }
            ),
        )
    )
    page = await _client().events("2026-10-06T10:00:00Z")
    assert page.next == "2026-10-06T10:00:12.512434831Z"
    assert page.more is True and page.reset is False
    assert [e.type for e in page.events] == ["upsert", "remove"]
    assert page.events[0].item is not None and page.events[1].item is None


@respx.mock
async def test_events_reset_has_no_events() -> None:
    respx.get(f"{BASE}/merchant/purchase/events").mock(
        return_value=httpx.Response(
            200, json=_ok({"since": "x", "next": "y", "count": 0, "more": False, "reset": True, "events": []})
        )
    )
    page = await _client().events("x")
    assert page.reset is True and page.events == []


@respx.mock
async def test_purchase_posts_json_and_parses_the_answer() -> None:
    route = respx.post(f"{BASE}/merchant/purchase").mock(
        return_value=httpx.Response(
            200,
            json=_ok(
                {
                    "id": 178,
                    "merchant_tx_id": "order-1",
                    "status": "pending",
                    "steam_id": "76561190000000001",
                    "amount": 45.99,
                    "date": "2026-10-06T10:30:00Z",
                    "item": {"id": "38029384123", "name": "x", "price": 45.99, "image_url": "https://i"},
                }
            ),
        )
    )
    p = await _client().purchase(
        asset_id="38029384123", partner=39734273, token="AbCdEf12", merchant_tx_id="order-1", max_price_usd=Decimal("46.00")
    )
    body = route.calls.last.request.read()
    assert b'"asset_id":"38029384123"' in body.replace(b" ", b"")
    assert b'"max_price":46.0' in body.replace(b" ", b"") or b'"max_price":46' in body.replace(b" ", b"")
    assert (p.id, p.status, p.amount_usd, p.asset_id) == (178, "pending", Decimal("45.99"), "38029384123")
    assert p.offer_id is None and p.fail_reason is None


@respx.mock
async def test_purchase_failed_answer_carries_the_reason() -> None:
    respx.post(f"{BASE}/merchant/purchase").mock(
        return_value=httpx.Response(
            200, json=_ok({"id": 179, "status": "failed", "fail_reason": "item_sold", "amount": 1.0, "date": "x"})
        )
    )
    p = await _client().purchase(asset_id="1", partner=39734273, token="AbCdEf12", merchant_tx_id="o", max_price_usd=Decimal(1))
    assert p.status == "failed" and p.fail_reason == "item_sold"


@respx.mock
async def test_validation_error_exposes_the_domain_code() -> None:
    respx.post(f"{BASE}/merchant/purchase").mock(
        return_value=httpx.Response(
            400,
            json={"success": False, "message": "validation error", "data": [{"field": "partner", "code": "trade_banned", "message": "x"}]},
        )
    )
    with pytest.raises(SkinslinkError) as exc:
        await _client().purchase(asset_id="1", partner=39734273, token="AbCdEf12", merchant_tx_id="o", max_price_usd=Decimal(1))
    assert exc.value.status == 400 and exc.value.code == "trade_banned"


@respx.mock
@pytest.mark.parametrize(("status", "error"), [(403, SkinslinkForbiddenError), (429, SkinslinkRateLimitedError), (500, SkinslinkUnavailableError), (502, SkinslinkUnavailableError), (408, SkinslinkUnavailableError)])
async def test_http_statuses_map_to_errors(status: int, error: type[Exception]) -> None:
    respx.get(f"{BASE}/merchant/balance").mock(return_value=httpx.Response(status, json={"success": False, "message": "x"}))
    with pytest.raises(error):
        await _client().balance()


@respx.mock
async def test_transport_failure_is_unavailable() -> None:
    respx.get(f"{BASE}/merchant/balance").mock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(SkinslinkUnavailableError):
        await _client().balance()


@respx.mock
async def test_status_404_is_none_and_balance_parses() -> None:
    respx.get(f"{BASE}/merchant/purchase/status").mock(return_value=httpx.Response(404, json={"success": False, "message": "not found"}))
    assert await _client().purchase_status(merchant_tx_id="nope") is None
    respx.get(f"{BASE}/merchant/balance").mock(return_value=httpx.Response(200, json=_ok({"total": 1250.75, "hold": 320.5, "available": 930.25})))
    b = await _client().balance()
    assert (b.total, b.hold, b.available) == (Decimal("1250.75"), Decimal("320.5"), Decimal("930.25"))


async def test_no_key_is_unavailable_without_a_call() -> None:
    with pytest.raises(SkinslinkUnavailableError):
        await SkinslinkClient(api_key="", base_url=BASE, timeout_seconds=1).balance()
```

- [ ] **Step 2: Run them**

Run: `cd apps/api && uv run pytest tests/contract/test_skinslink_client.py -q`
Expected: FAIL — `ImportError` from `skinslink.api`.

- [ ] **Step 3: Write the client**

`modules/skinslink/client.py` — structure (fill every function; no `Any` without the inline comment the codebase uses):

```python
"""Skinslink merchant API client (https://docs.skinslink.com/llm, read 2026-10-06).

``X-Api-Key`` on every call; the envelope is ``{success, message, data}``. Error bodies are
never logged (they echo the request). Amounts are USD as ``Decimal`` built from the JSON
text, never from a float.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

import httpx

from csmarket.core.config import Settings
from csmarket.core.logging import get_logger
from csmarket.core.metrics import record_skinslink_call

log = get_logger("csmarket.skinslink.client")

PURCHASE_FAIL_REASONS = frozenset(
    {"insufficient_balance", "price_changed", "item_sold", "item_not_available",
     "duplicate_purchase", "item_specified_price_not_found", "provider_unavailable"}
)
LINK_ERROR_CODES = frozenset(
    {"trade_link_revoked", "trade_link_invalid", "trade_banned", "profile_private",
     "limited_account", "hold", "permissions", "hold_and_permissions"}
)


class SkinslinkError(Exception):
    """Skinslink answered and said no (4xx, or ``success: false`` with a 200)."""

    def __init__(self, message: str, *, status: int, code: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code


class SkinslinkForbiddenError(SkinslinkError):
    """HTTP 403: the key is disabled or this host is not whitelisted."""


class SkinslinkUnavailableError(Exception):
    """No answer worth reading: transport, 408/5xx/502, an unreadable body, no key."""


class SkinslinkRateLimitedError(SkinslinkUnavailableError):
    """HTTP 429."""
```

Dataclasses as in Interfaces. Parsing helpers: `_decimal(v) -> Decimal | None` via `Decimal(str(v))` for int/float/str (never `Decimal(float)` directly — go through `str`); `_item(raw: Mapping[str, Any]) -> CatalogueItem | None` (needs `id` str/int and `name`; `price` → Decimal > 0; `phase` only if a non-empty str; `float` → float; `paint_seed` int; `inspect_url` only when it starts with `steam://`); `_purchase(raw) -> Purchase` (id int required else `SkinslinkUnavailableError("unexpected body")`; `offer_id` from `trade_offer_id`; `asset_id` from `item.id` or `asset_id`; `amount` → Decimal; `hold_end_date` str).

Transport:

```python
    async def _request(self, method: str, path: str, *, params=None, json_body=None, endpoint: str) -> Any:  # Any: Skinslink's JSON data, narrowed by each caller
        if not self._api_key:
            raise SkinslinkUnavailableError("no api key")
        try:
            async with self._session() as client:
                resp = await client.request(method, f"{self._base_url}{path}", params=params, json=json_body, headers={"X-Api-Key": self._api_key})
        except httpx.HTTPError as exc:
            record_skinslink_call(endpoint, "unavailable")
            raise SkinslinkUnavailableError(type(exc).__name__) from exc
        body = _json_or_none(resp)
        if resp.status_code == 429:
            record_skinslink_call(endpoint, "rate_limited"); raise SkinslinkRateLimitedError("rate limited")
        if resp.status_code == 403:
            record_skinslink_call(endpoint, "forbidden"); raise SkinslinkForbiddenError("forbidden", status=403)
        if resp.status_code in (408, 500, 502, 503, 504):
            record_skinslink_call(endpoint, "unavailable"); raise SkinslinkUnavailableError(f"http {resp.status_code}")
        if resp.status_code == 404:
            record_skinslink_call(endpoint, "not_found"); raise SkinslinkError("not found", status=404)
        if not isinstance(body, dict):
            record_skinslink_call(endpoint, "unavailable"); raise SkinslinkUnavailableError("unexpected body")
        if resp.status_code >= 400 or body.get("success") is not True:
            record_skinslink_call(endpoint, "refused")
            raise SkinslinkError(str(body.get("message", "error")), status=resp.status_code, code=_code(body))
        record_skinslink_call(endpoint, "ok")
        return body.get("data")
```

`_code(body)`: the first `data[].code` when `data` is a list of dicts; else `data.fail_reason` when a dict; else `None`.

Endpoints: `available` → `GET /merchant/purchase/available?game=csgo&full=true&extended=true` (`last_update_at` from `data`, fall back to `datetime.now(UTC).isoformat()` when absent — log `skinslink.available.no_cursor`); `events` → `GET /merchant/purchase/events?since=&game=&extended=true&limit=`; `purchase` → `POST /merchant/purchase` JSON `{"game":"csgo","asset_id":…,"partner":…,"token":…,"merchant_tx_id":…,"max_price": float(max_price_usd)}` — send `max_price` as a JSON number with two decimals (`float(max_price_usd.quantize(Decimal("0.01")))`); `purchase_status` → `GET /merchant/purchase/status?merchant_tx_id=` catching `SkinslinkError` with `status == 404` → `None`; `balance` → `GET /merchant/balance`.

`client_for(settings, *, timeout_seconds=None)` → `SkinslinkClient(api_key=settings.skinslink_api_key, base_url=settings.skinslink_base_url, timeout_seconds=timeout_seconds or settings.skinslink_request_timeout_seconds)`.

Metrics (`core/metrics.py`): add

```python
SkinslinkEndpoint = Literal["available", "events", "purchase", "status", "balance"]
SkinslinkOutcome = Literal["ok", "refused", "forbidden", "rate_limited", "unavailable", "not_found"]
SKINSLINK_CALLS = Counter("csmarket_skinslink_calls_total", "Skinslink API calls by endpoint and outcome.", ("endpoint", "outcome"))

def record_skinslink_call(endpoint: SkinslinkEndpoint, outcome: SkinslinkOutcome) -> None:
    """Count one Skinslink call by how it ended; values outside the sets become ``other``. Never raises."""
    _inc(SKINSLINK_CALLS, "csmarket_skinslink_calls_total", {"endpoint": endpoint if endpoint in _SKINSLINK_ENDPOINTS else "other", "outcome": outcome if outcome in _SKINSLINK_OUTCOMES else "other"})
```

with the two frozensets and `__all__` entries, following `record_waxpeer_call`.

`api.py` re-exports: the client class, the five dataclasses, the four errors, `PURCHASE_FAIL_REASONS`, `LINK_ERROR_CODES`, `client_for`.

- [ ] **Step 4: Run tests and gates**

Run: `cd apps/api && uv run pytest tests/contract/test_skinslink_client.py -q && cd ../.. && make lint typecheck`
Expected: 11 passed; clean.

- [ ] **Step 5: Commit**

```bash
git add apps/api/src/csmarket/modules/skinslink apps/api/src/csmarket/core/metrics.py apps/api/tests/contract/test_skinslink_client.py
git commit -m "feat(api/skinslink): the merchant API client — catalogue, events, purchase, status, balance"
```

---

### Task 3: Tables and the migration

**Files:**

- Create: `apps/api/src/csmarket/modules/skinslink/models.py`
- Create: `apps/api/migrations/versions/0018_skinslink.py`
- Modify: `apps/api/src/csmarket/modules/skins/models.py:69-84` (two columns)
- Modify: `apps/api/src/csmarket/modules/orders/models.py` (`source`, `offer_id`, nullable `listing_id`; renamed codes)
- Modify: `apps/api/src/csmarket/core/metrics.py` (renamed codes), `orders/buy_writes.py:24-28`, `orders/buying.py:313,382,394`, `orders/trade_view.py:46`, `orders/buy_writes.py:102`, `admin/orders_schemas.py:20`, `admin/orders_routes.py:166-206` (docstrings), tests that name the old codes (`grep -rn "waxpeer_low_balance\|waxpeer_forbidden" apps/api/tests apps/admin/src`)
- Modify: `apps/api/migrations/env.py`, `apps/scheduler/src/csmarket_scheduler/main.py`, `apps/worker/src/csmarket_worker/consumer.py` (model imports)
- Test: `apps/api/tests/integration/test_skinslink_models.py`

**Interfaces:**

- Produces (`skinslink/models.py`):
  - `SkinslinkItem` (`skinslink_items`): `id: str` PK (String(32)), `market_hash_name: str`, `phase: str` (`''` none), `price_units: int` (BigInteger; USD×1000), `float_value: Decimal | None` (Numeric(7,6)), `paint_seed: int | None`, `inspect_url: str | None`, `image_url: str | None`, `skin_item_id: str | None` FK `skin_items.id` ON DELETE SET NULL, `updated_at`. Index `ix_skinslink_items_item_price (skin_item_id, price_units)`.
  - `SkinslinkState` (`skinslink_state`): `id: int` PK (CHECK `id = 1`), `cursor: str | None`, `mirror_synced_at: datetime | None`, `full_loaded_at: datetime | None`.
  - `SkinslinkPurchase` (`skinslink_purchases`): `order_id` PK FK `orders.id` CASCADE, `asset_id: str`, `paid_units: int` (our cap), `purchase_id: int | None`, `status: str | None` (Skinslink's word), `offer_id: str | None` (Steam offer id), `fail_reason: str | None`, `amount_units: int | None`, `hold_end_date: datetime | None`, `buy_pending: bool` (default false), `buy_unconfirmed_at`, `attention_reason: str | None` (CHECK in `ATTENTION_REASONS`), `last_polled_at`, `resolved_at`, `resolved_by`, `resolved_note`, `created_at`, `updated_at`. Unique `purchase_id`.
  - `SkinslinkCheck` (`skinslink_checks`): `id: str` UUID PK, `purchase_id: int`, `created_at`, `claimed_at: datetime | None`. Index `(claimed_at, created_at)`.
  - `SKINSLINK_CHANNEL = "skinslink"`.
- `skin_items`: `skinslink_min_units: int | None` (BigInteger), `skinslink_count: int` (default 0).
- `orders`: `source: str` (String(12), default `'waxpeer'`, CHECK in `("waxpeer","skinslink")`), `offer_id: str | None` (String(48)), `listing_id` becomes nullable.
- `ORDER_SOURCES = ("waxpeer", "skinslink")` in `orders/models.py`.
- Renames everywhere: `waxpeer_low_balance` → `source_low_balance`; `waxpeer_forbidden` → `source_forbidden`.

- [ ] **Step 1: Write the failing test**

```python
# apps/api/tests/integration/test_skinslink_models.py
"""The Skinslink tables and the columns the second source adds (migration 0018)."""

from __future__ import annotations

import pytest
from csmarket.modules.orders.models import FAILURE_REASONS, ATTENTION_REASONS, Order
from csmarket.modules.skinslink.models import SkinslinkItem, SkinslinkPurchase, SkinslinkState
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.orders_factory import make_item_and_rate, make_order


async def test_mirror_rows_round_trip(db_session: AsyncSession) -> None:
    item, _ = await make_item_and_rate(db_session)
    db_session.add(SkinslinkItem(id="38029384123", market_hash_name=item.market_hash_name, phase="", price_units=12450, skin_item_id=item.id))
    db_session.add(SkinslinkState(id=1, cursor="2026-10-06T10:00:00Z"))
    await db_session.commit()
    row = await db_session.scalar(select(SkinslinkItem).where(SkinslinkItem.skin_item_id == item.id))
    assert row is not None and row.price_units == 12450


async def test_state_is_a_singleton(db_session: AsyncSession) -> None:
    db_session.add(SkinslinkState(id=2))
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


async def test_orders_default_to_waxpeer_and_accept_skinslink(db_session: AsyncSession) -> None:
    order = await make_order(db_session)
    assert order.source == "waxpeer"
    other = await make_order(db_session, source="skinslink", offer_id="sl:38029384123", listing_id=None)
    assert other.listing_id is None and other.offer_id == "sl:38029384123"
    db_session.add(SkinslinkPurchase(order_id=other.id, asset_id="38029384123", paid_units=12450, buy_pending=True))
    await db_session.commit()


async def test_source_is_checked(db_session: AsyncSession) -> None:
    with pytest.raises(IntegrityError):
        await make_order(db_session, source="ebay")
    await db_session.rollback()


def test_the_codes_lost_their_source_name() -> None:
    assert "source_low_balance" in FAILURE_REASONS and "waxpeer_low_balance" not in FAILURE_REASONS
    assert "source_forbidden" in ATTENTION_REASONS and "waxpeer_forbidden" not in ATTENTION_REASONS
```

(`make_order` passes `**overrides` to `Order(...)`: confirm in `orders_factory.build_order`; if it builds the row itself, add the three keyword passthroughs there.)

- [ ] **Step 2: Run it**

Run: `cd apps/api && uv run pytest tests/integration/test_skinslink_models.py -q`
Expected: FAIL — `ModuleNotFoundError: csmarket.modules.skinslink.models`.

- [ ] **Step 3: Models**

`skinslink/models.py` with the four classes above, `Base` from `csmarket.core.db`, the `_ts()`/`_at()` helpers copied as in `orders/models.py`, `ATTENTION_REASONS` imported from `csmarket.modules.orders.models` for the CHECK (the orders module never imports skinslink.models; this direction is fine).

`skins/models.py` after `count_all`:

```python
    # ---- the Skinslink side (same units), rolled up from ``skinslink_items`` every tick ----
    skinslink_min_units: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    skinslink_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
```

`orders/models.py`: `ORDER_SOURCES = ("waxpeer", "skinslink")`; columns

```python
    #: Which market the chosen offer is on (spec 2026-10-06).
    source: Mapped[str] = mapped_column(String(12), nullable=False, server_default=text("'waxpeer'"))
    #: The prefixed offer id (``wx:<item_id>`` / ``sl:<asset_id>``); ``NULL`` on pre-0018 rows.
    offer_id: Mapped[str | None] = mapped_column(String(48), nullable=True)
    #: The Waxpeer offer the buyer chose (``NULL`` for a Skinslink order).
    listing_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
```

plus `CheckConstraint(f"source IN {_in(ORDER_SOURCES)}", name="source")`; `FAILURE_REASONS = ("sold_out", "source_low_balance", "invalid_trade_link", "not_accepted", "admin")`; `ATTENTION_REASONS` with `"source_forbidden"`.

Rename the two codes in `core/metrics.py` (`OrderRefundReason`, `_ORDER_REFUND_REASONS`, `TradeAttentionReason`, `_TRADE_ATTENTION_REASONS`), `orders/buy_writes.py` (`_REFUND_OUTCOMES`, `_settle`), `orders/buying.py` (three call sites), `orders/trade_view.py` (`_FAILURE_REASONS`), `admin/orders_schemas.py:20`, docstrings in `admin/orders_routes.py`, and every test that names them (`grep -rln "waxpeer_low_balance\|waxpeer_forbidden" apps/api/tests apps/admin/src packages/i18n/locales` — admin labels in `packages/i18n/locales/*/admin.json` keep the user-facing text, only the key changes). Alert `WaxpeerForbidden` in `infra/prometheus/alerts/orders.yml` keys on `outcome="forbidden"`, unchanged.

Migration `0018_skinslink.py`:

```python
"""skinslink: the mirror, state, purchases and checks; skin_items and orders learn a second source

Revision ID: 0018_skinslink
Revises: 0017_orders_trade_link_erased
Create Date: 2026-10-06
"""
```

`upgrade()`: create the four tables (with the indexes and checks above); `op.add_column("skin_items", …skinslink_min_units…)`, `…skinslink_count… server_default="0"`; `op.add_column("orders", "source" … server_default="'waxpeer'")`, `"offer_id"`, `op.alter_column("orders", "listing_id", nullable=True)`, `op.create_check_constraint("ck_orders_source", "orders", "source IN ('waxpeer','skinslink')")`; backfill `UPDATE orders SET offer_id = 'wx:' || listing_id WHERE offer_id IS NULL AND listing_id IS NOT NULL`; `UPDATE orders SET failure_reason='source_low_balance' WHERE failure_reason='waxpeer_low_balance'`; `UPDATE skin_trades SET attention_reason='source_forbidden' WHERE attention_reason='waxpeer_forbidden'`; drop and recreate `ck_skin_trades_attention_reason` with the new list (check the constraint's real name with `\d skin_trades` in `make psql`; the metadata convention is `ck_<table>_<name>`). `downgrade()`: the reverse (map the codes back, drop columns and tables).

Model imports: `migrations/env.py` (`from csmarket.modules.skinslink import models as _skinslink_models  # noqa: F401`), `scheduler/main.py`, `worker/consumer.py` the same way.

- [ ] **Step 4: Migrate the dev DB and run the tests**

Run: `make migrate && cd apps/api && uv run pytest tests/integration/test_skinslink_models.py tests/integration/test_orders_models.py tests/unit/test_orders_vocabulary.py -q && cd ../.. && make lint typecheck`
Expected: PASS (the integration suite starts its own Postgres and runs Alembic head); clean.

Also: `cd apps/api && uv run pytest tests -q -x -k "orders or admin" -p no:cacheprovider` — the renames must leave the orders and admin suites green.

- [ ] **Step 5: Commit**

```bash
git add apps/api/src apps/api/migrations apps/api/tests apps/scheduler/src/csmarket_scheduler/main.py apps/worker/src/csmarket_worker/consumer.py packages/i18n/locales
git commit -m "feat(api/skinslink): tables for the mirror, purchases and checks; orders carry a source

Failure and attention codes lose the Waxpeer name (source_low_balance,
source_forbidden) — both sources share them; 0018 maps the old rows."
```

---

### Task 4: The mirror and its scheduler job

**Files:**

- Create: `apps/api/src/csmarket/modules/skinslink/mirror.py`
- Create: `apps/scheduler/src/csmarket_scheduler/jobs/skinslink_mirror.py`
- Modify: `apps/scheduler/src/csmarket_scheduler/main.py:58-71`, `apps/api/src/csmarket/modules/skinslink/api.py`
- Modify: `apps/api/src/csmarket/core/metrics.py` (gauge `csmarket_skinslink_mirror_synced_timestamp_seconds`, `set_skinslink_mirror_synced()`)
- Test: `apps/api/tests/integration/test_skinslink_mirror.py`, `apps/scheduler/tests/test_skinslink_mirror_job.py`

**Interfaces:**

- Produces (`mirror.py`): `async def sync_mirror(db_factory: Callable[[], AsyncSession], client: SkinslinkClient, *, now: datetime) -> MirrorResult` where `MirrorResult(frozen)` has `mode: Literal["full","events","reset","skipped"]`, `upserts: int`, `removes: int`, `pages: int`; `async def mirror_fresh(db: AsyncSession, *, settings: Settings, now: datetime) -> bool` (synced within `skinslink_mirror_stale_minutes`); `def to_units(price_usd: Decimal) -> int` (`int((price_usd * 1000).quantize(Decimal(1), ROUND_HALF_UP))`); `def split_phase(name: str, phase: str | None) -> tuple[str, str]` (Skinslink's `name` already **without** the phase plus `phase` separately → our `(market_hash_name, phase)`; a Doppler/Gamma Doppler with no phase → `phase=""` and the item stays unmapped).
- Mapping rule: `skin_item_id = (SELECT id FROM skin_items WHERE market_hash_name=:name AND phase=:phase)` at upsert; unmapped rows keep `skin_item_id NULL`.
- Consumes: `SkinslinkClient.available/events`, `CatalogueItem`, `EventsPage` (Task 2); models (Task 3).

- [ ] **Step 1: Write the failing tests**

```python
# apps/api/tests/integration/test_skinslink_mirror.py
"""The mirror of Skinslink's stock: full load, events, reset, staleness, mapping."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from csmarket.core.config import get_settings
from csmarket.modules.skinslink.api import AvailablePage, CatalogueEvent, CatalogueItem, EventsPage
from csmarket.modules.skinslink.mirror import mirror_fresh, split_phase, sync_mirror, to_units
from csmarket.modules.skinslink.models import SkinslinkItem, SkinslinkState
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.orders_factory import make_item_and_rate

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)


def _item(id_: str, name: str, price: str, phase: str | None = None) -> CatalogueItem:
    return CatalogueItem(id=id_, name=name, price_usd=Decimal(price), image_url="https://i/x.png", phase=phase, float_value=0.2, paint_seed=1, inspect_url=None)


class ScriptedClient:
    """Answers in order; records what it was asked."""

    def __init__(self, *answers: AvailablePage | EventsPage) -> None:
        self.answers = list(answers)
        self.asked: list[tuple[str, str | None]] = []

    async def available(self, game: str = "csgo") -> AvailablePage:
        self.asked.append(("available", None))
        a = self.answers.pop(0)
        assert isinstance(a, AvailablePage)
        return a

    async def events(self, since: str, *, game: str = "csgo", limit: int = 10000) -> EventsPage:
        self.asked.append(("events", since))
        a = self.answers.pop(0)
        assert isinstance(a, EventsPage)
        return a


def _factory(db: AsyncSession):  # noqa: ANN202 -- a test helper returning the session's maker
    return lambda: db


async def test_first_tick_loads_everything_and_maps_known_names(db_session: AsyncSession) -> None:
    item, _ = await make_item_and_rate(db_session)
    client = ScriptedClient(AvailablePage(items=[_item("1", item.market_hash_name, "12.45"), _item("2", "Nope | Nothing (Field-Tested)", "1.00")], last_update_at="2026-10-06T11:59:00Z"))
    result = await sync_mirror(_factory(db_session), client, now=NOW)  # type: ignore[arg-type]
    assert (result.mode, result.upserts) == ("full", 2)
    rows = {r.id: r for r in (await db_session.scalars(select(SkinslinkItem))).all()}
    assert rows["1"].skin_item_id == item.id and rows["1"].price_units == 12450
    assert rows["2"].skin_item_id is None
    state = await db_session.get(SkinslinkState, 1)
    assert state is not None and state.cursor == "2026-10-06T11:59:00Z" and state.mirror_synced_at == NOW


async def test_events_apply_upsert_and_remove_and_follow_more(db_session: AsyncSession) -> None:
    item, _ = await make_item_and_rate(db_session)
    first = AvailablePage(items=[_item("1", item.market_hash_name, "10.00")], last_update_at="c0")
    page1 = EventsPage(since="c0", next="c1", more=True, reset=False, events=[CatalogueEvent(type="upsert", at="x", id="1", item=_item("1", item.market_hash_name, "9.00"))])
    page2 = EventsPage(since="c1", next="c2", more=False, reset=False, events=[CatalogueEvent(type="remove", at="x", id="1", item=None), CatalogueEvent(type="upsert", at="x", id="3", item=_item("3", item.market_hash_name, "8.00"))])
    client = ScriptedClient(first, page1, page2)
    await sync_mirror(_factory(db_session), client, now=NOW)  # type: ignore[arg-type]
    result = await sync_mirror(_factory(db_session), client, now=NOW + timedelta(seconds=15))  # type: ignore[arg-type]
    assert (result.mode, result.pages, result.upserts, result.removes) == ("events", 2, 2, 1)
    assert client.asked[1:] == [("events", "c0"), ("events", "c1")]
    ids = sorted(r.id for r in (await db_session.scalars(select(SkinslinkItem))).all())
    assert ids == ["3"]
    state = await db_session.get(SkinslinkState, 1)
    assert state is not None and state.cursor == "c2"


async def test_reset_reloads_everything(db_session: AsyncSession) -> None:
    item, _ = await make_item_and_rate(db_session)
    client = ScriptedClient(
        AvailablePage(items=[_item("1", item.market_hash_name, "10.00")], last_update_at="c0"),
        EventsPage(since="c0", next="c0", more=False, reset=True, events=[]),
        AvailablePage(items=[_item("9", item.market_hash_name, "7.00")], last_update_at="c9"),
    )
    await sync_mirror(_factory(db_session), client, now=NOW)  # type: ignore[arg-type]
    result = await sync_mirror(_factory(db_session), client, now=NOW)  # type: ignore[arg-type]
    assert result.mode == "reset"
    ids = [r.id for r in (await db_session.scalars(select(SkinslinkItem))).all()]
    assert ids == ["9"]


async def test_unmapped_items_are_kept_but_never_offered(db_session: AsyncSession) -> None:
    client = ScriptedClient(AvailablePage(items=[_item("1", "★ Karambit | Doppler (Factory New)", "900.00", phase=None)], last_update_at="c0"))
    await sync_mirror(_factory(db_session), client, now=NOW)  # type: ignore[arg-type]
    row = await db_session.get(SkinslinkItem, "1")
    assert row is not None and row.skin_item_id is None and row.phase == ""


async def test_mirror_fresh_follows_the_stale_minutes(db_session: AsyncSession) -> None:
    settings = get_settings()
    assert await mirror_fresh(db_session, settings=settings, now=NOW) is False  # never synced
    db_session.add(SkinslinkState(id=1, mirror_synced_at=NOW - timedelta(minutes=9)))
    await db_session.commit()
    assert await mirror_fresh(db_session, settings=settings, now=NOW) is True
    assert await mirror_fresh(db_session, settings=settings, now=NOW + timedelta(minutes=2)) is False


def test_units_and_phase() -> None:
    assert to_units(Decimal("12.45")) == 12450
    assert to_units(Decimal("0.0005")) == 1
    assert split_phase("★ Karambit | Doppler (Factory New)", "Phase 2") == ("★ Karambit | Doppler (Factory New)", "Phase 2")
    assert split_phase("AK-47 | Redline (Field-Tested)", None) == ("AK-47 | Redline (Field-Tested)", "")
```

- [ ] **Step 2: Run them**

Run: `cd apps/api && uv run pytest tests/integration/test_skinslink_mirror.py -q`
Expected: FAIL — `ModuleNotFoundError: csmarket.modules.skinslink.mirror`.

- [ ] **Step 3: Write the mirror**

`mirror.py` outline:

```python
async def sync_mirror(db_factory, client, *, now) -> MirrorResult:
    async with db_factory() as db:
        state = await db.get(SkinslinkState, 1) or SkinslinkState(id=1)
        cursor = state.cursor
    if cursor is None:
        return await _full(db_factory, client, now=now, mode="full")
    pages = upserts = removes = 0
    since = cursor
    while True:
        page = await client.events(since)
        pages += 1
        if page.reset:
            return await _full(db_factory, client, now=now, mode="reset")
        async with db_factory() as db:
            u, r = await _apply_events(db, page.events)
            await _touch(db, cursor=page.next, now=now)
            await db.commit()
        upserts += u; removes += r; since = page.next
        if not page.more or pages >= MAX_PAGES_PER_TICK:  # 20
            break
    return MirrorResult(mode="events", upserts=upserts, removes=removes, pages=pages)
```

`_full`: `page = await client.available()`; in one transaction `DELETE FROM skinslink_items`, bulk upsert (`pg_insert(...).on_conflict_do_update` by `id`, batches of 1000) with `skin_item_id` resolved by one `SELECT id, market_hash_name, phase FROM skin_items WHERE (market_hash_name, phase) IN (...)` per batch (build a dict), `_touch(db, cursor=page.last_update_at, now=now, full=True)`; `MirrorResult(mode=…, upserts=len(items), removes=0, pages=1)`.

`_apply_events`: upserts via the same bulk upsert, removes via `DELETE WHERE id IN (...)`; re-applying is safe (upsert by id, delete of a missing id is 0 rows).

`_touch` writes `SkinslinkState` row 1: `cursor`, `mirror_synced_at=now`, `full_loaded_at=now` when `full`.

`mirror_fresh`: `synced = await db.scalar(select(SkinslinkState.mirror_synced_at).where(SkinslinkState.id == 1))`; `return synced is not None and now - synced <= timedelta(minutes=settings.skinslink_mirror_stale_minutes)`.

Rows: `float_value` → `Decimal(str(float))` quantized to 6 places; `price_units=to_units(item.price_usd)`; `phase` via `split_phase`.

Metrics: `set_skinslink_mirror_synced()` sets the gauge to `time.time()` after a successful tick (job calls it).

Scheduler job `jobs/skinslink_mirror.py` (model: `skins_price_sync.py`): `JOB_ID = "skinslink.mirror"`; `run()` returns at once unless `get_settings().skinslink_active`; builds `client_for(settings)`; calls `sync_mirror(get_session_factory(), client, now=now())`; on `SkinslinkUnavailableError`/`SkinslinkError`/`SkinslinkRateLimitedError` logs `skinslink.mirror.failed` with the error type only; `set_skinslink_mirror_synced()` on success; `register()` every 15 seconds, `next_run_time=first_run_after(45)`, `coalesce=True`, `max_instances=1`. Add `skinslink_mirror.register(scheduler)` to `build_scheduler` after `skins_price_sync`.

`apps/scheduler/tests/test_skinslink_mirror_job.py`: with `skinslink_enabled=False` (monkeypatch `get_settings`), `run()` makes no client (patch `client_for` to raise) and logs `skinslink.mirror.skipped`; with a scripted `sync_mirror` raising `SkinslinkUnavailableError`, `run()` returns without raising. Follow `apps/scheduler/tests/test_skins_price_sync_job.py` if it exists for the fixture style.

`api.py` adds: `sync_mirror`, `mirror_fresh`, `to_units`, `MirrorResult`, `SKINSLINK_CHANNEL`, the models.

- [ ] **Step 4: Run tests and gates**

Run: `cd apps/api && uv run pytest tests/integration/test_skinslink_mirror.py -q && cd ../scheduler && uv run pytest tests/test_skinslink_mirror_job.py -q && cd ../.. && make lint typecheck`
Expected: PASS; clean.

- [ ] **Step 5: Commit**

```bash
git add apps/api/src/csmarket/modules/skinslink apps/api/src/csmarket/core/metrics.py apps/scheduler/src apps/scheduler/tests apps/api/tests/integration/test_skinslink_mirror.py
git commit -m "feat(api/skinslink): a mirror of Skinslink's stock, kept current by the events feed every 15 s"
```

---

### Task 5: Source-neutral offers, Skinslink offers, the merged listings route

**Files:**

- Create: `apps/api/src/csmarket/modules/skins/offers.py`
- Create: `apps/api/src/csmarket/modules/skinslink/offers.py`
- Modify: `apps/api/src/csmarket/modules/skins/routes.py:299-361` (`get_listings`), `skins/schemas.py:113-123` (`listing_id: str`, `SkinListingSummaryOut.listing_id: str`), `skins/api.py`, `skinslink/api.py`, `skins/service.py` (where `cheapest` summaries are built: prefix `wx:`)
- Test: `apps/api/tests/unit/test_skins_offers.py`, `apps/api/tests/integration/test_skinslink_offers.py`, update `apps/api/tests/integration/test_skins_listings_route.py` (ids are `wx:<n>` strings now)

**Interfaces:**

- Produces (`skins/offers.py`):
  - `Source = Literal["waxpeer", "skinslink"]`
  - `@dataclass(frozen=True) Offer(offer_id: str, source: Source, price_units: int, float_value: float | None, paint_seed: int | None, stickers: list[dict[str, Any]], inspect_url: str | None, listing_id: int | None = None, asset_id: str | None = None)`
  - `def offer_id_of(source: Source, raw: int | str) -> str` → `"wx:123"` / `"sl:380…"`
  - `def parse_offer_id(value: str | int) -> tuple[Source, str]`; a bare int or an all-digit string → `("waxpeer", "123")`; raises `ValueError` on anything else.
  - `def from_listing(l: Listing) -> Offer`
  - `def merge_offers(*groups: Sequence[Offer]) -> list[Offer]` sorted by `(price_units, source != "waxpeer", offer_id)` (Waxpeer first on a tie: instant delivery).
- Produces (`skinslink/offers.py`): `async def offers_for(db: AsyncSession, skin_item_id: str, *, settings: Settings, now: datetime) -> list[Offer]` — `[]` unless `settings.skinslink_active` and `mirror_fresh(...)`; else every `skinslink_items` row of that item as `Offer(source="skinslink", offer_id="sl:"+id, asset_id=id, stickers=[])`, ordered by price.
- Route: `GET /skins/{slug}/listings` returns Waxpeer offers (as today) merged with Skinslink's; `listing_id` is the prefixed string.

- [ ] **Step 1: Write the failing tests**

```python
# apps/api/tests/unit/test_skins_offers.py
from __future__ import annotations

import pytest
from csmarket.modules.skins.listings import Listing
from csmarket.modules.skins.offers import Offer, from_listing, merge_offers, offer_id_of, parse_offer_id


def _o(source: str, price: int, raw: str) -> Offer:
    return Offer(offer_id=offer_id_of(source, raw), source=source, price_units=price, float_value=None, paint_seed=None, stickers=[], inspect_url=None)  # type: ignore[arg-type]


def test_ids_round_trip() -> None:
    assert offer_id_of("waxpeer", 123) == "wx:123"
    assert offer_id_of("skinslink", "38029384123") == "sl:38029384123"
    assert parse_offer_id("wx:123") == ("waxpeer", "123")
    assert parse_offer_id("sl:38029384123") == ("skinslink", "38029384123")
    assert parse_offer_id(123) == ("waxpeer", "123")  # one release of the old integer
    assert parse_offer_id("123") == ("waxpeer", "123")


@pytest.mark.parametrize("bad", ["ebay:1", "wx:", "sl:", "wx:abc", "", "x"])
def test_bad_ids_are_refused(bad: str) -> None:
    with pytest.raises(ValueError, match="offer id"):
        parse_offer_id(bad)


def test_merge_sorts_by_price_then_waxpeer_first() -> None:
    merged = merge_offers([_o("waxpeer", 1200, "2"), _o("waxpeer", 1000, "1")], [_o("skinslink", 1000, "a"), _o("skinslink", 900, "b")])
    assert [o.offer_id for o in merged] == ["sl:b", "wx:1", "sl:a", "wx:2"]


def test_from_listing_keeps_the_fields() -> None:
    l = Listing(listing_id=7, price_units=5000, float_value=0.1, paint_seed=3, stickers=[{"name": "s"}], inspect_url="steam://x", delivery=None)
    o = from_listing(l)
    assert (o.offer_id, o.source, o.listing_id, o.price_units, o.stickers) == ("wx:7", "waxpeer", 7, 5000, [{"name": "s"}])
```

```python
# apps/api/tests/integration/test_skinslink_offers.py
"""Skinslink offers come from the mirror; none when disabled or stale."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from csmarket.core.config import get_settings
from csmarket.modules.skinslink.models import SkinslinkItem, SkinslinkState
from csmarket.modules.skinslink.offers import offers_for
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.orders_factory import make_item_and_rate

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
ACTIVE = {"skinslink_enabled": True, "skinslink_api_key": "k", "skinslink_secret": "s"}


async def _seed(db: AsyncSession, synced_at: datetime) -> str:
    item, _ = await make_item_and_rate(db)
    db.add_all([
        SkinslinkItem(id="b", market_hash_name=item.market_hash_name, phase="", price_units=9000, skin_item_id=item.id, float_value=None),
        SkinslinkItem(id="a", market_hash_name=item.market_hash_name, phase="", price_units=8000, skin_item_id=item.id, float_value=None),
        SkinslinkState(id=1, mirror_synced_at=synced_at, cursor="c"),
    ])
    await db.commit()
    return item.id


async def test_offers_sorted_by_price_with_prefixed_ids(db_session: AsyncSession) -> None:
    item_id = await _seed(db_session, NOW)
    offers = await offers_for(db_session, item_id, settings=get_settings().model_copy(update=ACTIVE), now=NOW)
    assert [(o.offer_id, o.price_units, o.source, o.asset_id) for o in offers] == [("sl:a", 8000, "skinslink", "a"), ("sl:b", 9000, "skinslink", "b")]


async def test_disabled_offers_nothing(db_session: AsyncSession) -> None:
    item_id = await _seed(db_session, NOW)
    assert await offers_for(db_session, item_id, settings=get_settings(), now=NOW) == []


async def test_stale_mirror_offers_nothing(db_session: AsyncSession) -> None:
    item_id = await _seed(db_session, NOW - timedelta(minutes=11))
    assert await offers_for(db_session, item_id, settings=get_settings().model_copy(update=ACTIVE), now=NOW) == []
```

Route test additions (`test_skins_listings_route.py`): the existing assertions on `listing_id` become `"wx:<n>"`; add one test that seeds a fresh mirror row for the item under active settings (override `get_settings` the way the suite already does) and asserts the merged list contains both `wx:` and `sl:` ids sorted by `price_uzs`, and that the Skinslink entry has `stickers == []`.

- [ ] **Step 2: Run them**

Run: `cd apps/api && uv run pytest tests/unit/test_skins_offers.py tests/integration/test_skinslink_offers.py -q`
Expected: FAIL — modules missing.

- [ ] **Step 3: Implement**

`skins/offers.py` as in Interfaces. `parse_offer_id`:

```python
_PREFIX: dict[str, Source] = {"wx": "waxpeer", "sl": "skinslink"}

def parse_offer_id(value: str | int) -> tuple[Source, str]:
    """``("waxpeer", "123")`` for ``"wx:123"`` or a bare integer; ``("skinslink", id)`` for ``"sl:…"``.

    Raises:
        ValueError: anything else (an unknown prefix, an empty or non-numeric id).
    """
    text = str(value)
    if text.isdigit():
        return "waxpeer", text
    prefix, sep, raw = text.partition(":")
    source = _PREFIX.get(prefix)
    if not sep or source is None or not raw or not raw.isdigit():
        raise ValueError(f"not an offer id: {text!r}")
    return source, raw
```

`skinslink/offers.py` per Interfaces (one `SELECT` ordered by `price_units, id`, after `mirror_fresh`).

`skins/schemas.py`: `SkinListingOut.listing_id: str`, `SkinListingSummaryOut.listing_id: str`. `skins/service.py` (or wherever `cheapest` is built from `cheapest_auto`): `listing_id=offer_id_of("waxpeer", e["listing_id"])`.

`skins/routes.py:get_listings`: after `listings_for`, `extra = await offers_for(db, item.id, settings=settings, now=now())` (import from `csmarket.modules.skinslink.api`); `offers = merge_offers([from_listing(r) for r in rows], extra)`; build each `SkinListingOut` from the `Offer` (`listing_id=o.offer_id`). Keep the quote per offer as today (`quote(o.price_units, …)`). Note the dependency in the module docstring: "the route composes two modules' reads; `skins` itself never imports `skinslink`".

`skins/api.py` exports `Offer`, `Source`, `offer_id_of`, `parse_offer_id`, `from_listing`, `merge_offers`. `skinslink/api.py` exports `offers_for`.

Then `make gen-api` (the `listing_id` type changes) and commit the generated files.

- [ ] **Step 4: Run tests and gates**

Run: `cd apps/api && uv run pytest tests/unit/test_skins_offers.py tests/integration/test_skinslink_offers.py tests/integration/test_skins_listings_route.py tests/integration/test_skins_catalog_routes.py -q && cd ../.. && make lint typecheck && make gen-api && git status --short docs/api packages/api-client`
Expected: PASS; clean; `openapi.json` and the client changed.

- [ ] **Step 5: Commit**

```bash
git add apps/api/src apps/api/tests docs/api/openapi.json packages/api-client
git commit -m "feat(api/skins): source-neutral offers (wx:/sl: ids); Skinslink offers join the listings from the mirror"
```

---

### Task 6: Prices from the cheaper source

**Files:**

- Create: `apps/api/src/csmarket/modules/skinslink/rollup.py`
- Modify: `apps/api/src/csmarket/modules/skins/prices.py:245-270` (deactivation) and `:273-314` (`sync_prices`), `skins/repricing.py:42-92`, `skins/schemas.py` (`count`), `skins/service.py` (wherever `count=item.count_auto` is mapped)
- Test: `apps/api/tests/integration/test_skinslink_rollup.py`, `apps/api/tests/unit/test_skins_reprice_cost.py`, update `test_skins_price_sync.py` if it asserts `active` after deactivation

**Interfaces:**

- Produces (`skinslink/rollup.py`): `async def rollup(db: AsyncSession, *, settings: Settings, now: datetime) -> int` — when `skinslink_active` and `mirror_fresh`: one `UPDATE skin_items SET skinslink_min_units = agg.min, skinslink_count = agg.count, active = TRUE FROM (SELECT skin_item_id, MIN(price_units), COUNT(*) FROM skinslink_items WHERE skin_item_id IS NOT NULL GROUP BY skin_item_id) agg WHERE skin_items.id = agg.skin_item_id`, then `UPDATE skin_items SET skinslink_min_units = NULL, skinslink_count = 0 WHERE skinslink_count > 0 AND id NOT IN (agg ids)` and `active = (count_auto > 0)` for those; otherwise (disabled or stale) clear every row's two columns and set `active = count_auto > 0` where `skinslink_count > 0` was. Returns rows touched. Exported through `skinslink/api.py`.
- `skins/repricing.py`: cost = `LEAST(min_auto_units, skinslink_min_units)` (either may be NULL) and `count_auto + skinslink_count` as the liquidity count passed to `quote` (`count_auto=` keyword stays, value is the sum); a row with both NULL → price NULL.
- `skins/prices.py:apply_prices`: the deactivation `UPDATE` adds `SkinItem.skinslink_count == 0` to its `WHERE`; `sync_prices` calls `rollup(db, settings=get_settings(), now=now())` after `apply_prices` and before `reprice_rows`.
- Catalogue `count` = `count_auto + skinslink_count` (`SkinItemOut` built in `skins/service.py`).

- [ ] **Step 1: Write the failing tests**

```python
# apps/api/tests/integration/test_skinslink_rollup.py
"""Prices come from the cheaper source; a stale or disabled mirror prices nothing."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from csmarket.core.config import get_settings
from csmarket.modules.skins.models import SkinItem
from csmarket.modules.skins.repricing import reprice_rows
from csmarket.modules.skins.settings import load_rules
from csmarket.modules.skinslink.models import SkinslinkItem, SkinslinkState
from csmarket.modules.skinslink.rollup import rollup
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.orders_factory import make_item_and_rate

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
ACTIVE = {"skinslink_enabled": True, "skinslink_api_key": "k", "skinslink_secret": "s"}


async def _mirror(db: AsyncSession, item: SkinItem, prices: list[int], synced: datetime = NOW) -> None:
    db.add_all([SkinslinkItem(id=f"a{i}", market_hash_name=item.market_hash_name, phase=item.phase, price_units=p, skin_item_id=item.id) for i, p in enumerate(prices)])
    db.add(SkinslinkState(id=1, mirror_synced_at=synced, cursor="c"))
    await db.commit()


async def test_rollup_writes_min_and_count_and_the_cheaper_source_prices(db_session: AsyncSession) -> None:
    item, _ = await make_item_and_rate(db_session)  # orders_factory: min_auto_units=12_345, count_auto>0
    await _mirror(db_session, item, [11_000, 15_000])
    settings = get_settings().model_copy(update=ACTIVE)
    assert await rollup(db_session, settings=settings, now=NOW) == 1
    before = item.sell_price_usd
    await reprice_rows(db_session, await load_rules(db_session))
    await db_session.commit()
    await db_session.refresh(item)
    assert (item.skinslink_min_units, item.skinslink_count) == (11_000, 2)
    assert item.sell_price_usd is not None and before is not None and item.sell_price_usd < before


async def test_skinslink_only_item_becomes_active(db_session: AsyncSession) -> None:
    item, _ = await make_item_and_rate(db_session)
    item.min_auto_units, item.count_auto, item.active = None, 0, False
    await db_session.commit()
    await _mirror(db_session, item, [5_000])
    await rollup(db_session, settings=get_settings().model_copy(update=ACTIVE), now=NOW)
    await reprice_rows(db_session, await load_rules(db_session))
    await db_session.commit()
    await db_session.refresh(item)
    assert item.active is True and item.sell_price_usd is not None


async def test_stale_mirror_does_not_price(db_session: AsyncSession) -> None:
    item, _ = await make_item_and_rate(db_session)
    await _mirror(db_session, item, [1_000], synced=NOW - timedelta(minutes=11))
    settings = get_settings().model_copy(update=ACTIVE)
    await rollup(db_session, settings=settings, now=NOW)
    await db_session.commit()
    await db_session.refresh(item)
    assert (item.skinslink_min_units, item.skinslink_count, item.active) == (None, 0, True)  # Waxpeer stock keeps it active


async def test_disabled_clears_an_earlier_rollup(db_session: AsyncSession) -> None:
    item, _ = await make_item_and_rate(db_session)
    await _mirror(db_session, item, [1_000])
    await rollup(db_session, settings=get_settings().model_copy(update=ACTIVE), now=NOW)
    await rollup(db_session, settings=get_settings(), now=NOW)
    await db_session.commit()
    await db_session.refresh(item)
    assert (item.skinslink_min_units, item.skinslink_count) == (None, 0)
```

```python
# apps/api/tests/unit/test_skins_reprice_cost.py
from __future__ import annotations

from csmarket.modules.skins.repricing import cost_units


def test_cost_is_the_cheaper_source_or_the_one_present() -> None:
    assert cost_units(12_345, 11_000) == 11_000
    assert cost_units(12_345, None) == 12_345
    assert cost_units(None, 9_000) == 9_000
    assert cost_units(None, None) is None
```

- [ ] **Step 2: Run them**

Run: `cd apps/api && uv run pytest tests/integration/test_skinslink_rollup.py tests/unit/test_skins_reprice_cost.py -q`
Expected: FAIL — `rollup` / `cost_units` missing.

- [ ] **Step 3: Implement**

`skins/repricing.py`: add

```python
def cost_units(waxpeer: int | None, skinslink: int | None) -> int | None:
    """The cheaper source's units, or the one that has stock; ``None`` with neither."""
    present = [u for u in (waxpeer, skinslink) if u is not None]
    return min(present) if present else None
```

`reprice_rows`: select `SkinItem.skinslink_min_units`, `SkinItem.skinslink_count` too; `units = cost_units(row.min_auto_units, row.skinslink_min_units)`; `if units is None: price, discount = None, None` else `quote(units, …, count_auto=row.count_auto + row.skinslink_count, …)`.

`skinslink/rollup.py` as in Interfaces (plain SQLAlchemy Core: a subquery with `func.min`, `func.count`, two `update()` statements, then the clearing branch). `sync_prices` gets the call; `apply_prices` deactivation adds `SkinItem.skinslink_count == 0`.

Catalogue `count`: where `SkinItemOut` is built (`skins/service.py`, grep `count=`), use `item.count_auto + item.skinslink_count`.

- [ ] **Step 4: Run tests and gates**

Run: `cd apps/api && uv run pytest tests/integration/test_skinslink_rollup.py tests/unit/test_skins_reprice_cost.py tests/integration/test_skins_price_sync.py tests/integration/test_skins_reprice.py tests/integration/test_skins_catalog_routes.py -q && cd ../.. && make lint typecheck`
Expected: PASS; clean.

- [ ] **Step 5: Commit**

```bash
git add apps/api/src apps/api/tests
git commit -m "feat(api/skins): the catalogue is priced from the cheaper source; Skinslink stock rolls up every price tick"
```

---

### Task 7: Checkout across sources

**Files:**

- Modify: `apps/api/src/csmarket/modules/orders/schemas.py:17-27` (`listing_id: int | str`), `orders/checkout.py` (offers, `_choose`, `_build`), `orders/api.py` if it re-exports anything new
- Modify: `docs/api/README.md` (`POST /orders`: `listing_id` is `wx:<id>`/`sl:<id>`, a bare integer still accepted; `next_offer.listing_id` is the same string)
- Test: update `apps/api/tests/integration/test_orders_checkout.py`; add `test_orders_checkout_sources.py`

**Interfaces:**

- `OrderCreateIn.listing_id: Annotated[int | str, Field(...)]` with a validator `parse_offer_id` (422 on a bad id; message `not an offer id`).
- `create_order` builds `offers = merge_offers([from_listing(r) for r in rows], await offers_for(db, snap.id, settings=settings, now=now()))` — the Skinslink read happens **before** `db.rollback()` releases the connection (it is a DB read); the Waxpeer read after, as today.
- `_choose(priced: list[tuple[Offer, (usd, uzs)]], body, settings, rate)` matches by `offer_id`; `next_offer = {"listing_id": cheapest.offer_id, "price_uzs": …}`.
- `_build` writes `source=row.source`, `offer_id=row.offer_id`, `listing_id=row.listing_id` (None for Skinslink), `cost_units=row.price_units`, `cost_usd` as today.
- `created` log adds `source=row.source`.

- [ ] **Step 1: Write the failing tests**

```python
# apps/api/tests/integration/test_orders_checkout_sources.py
"""POST /orders with a Skinslink offer, a bare integer id, and a next offer across sources."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from csmarket.core.config import get_settings
from csmarket.modules.orders.models import Order
from csmarket.modules.skinslink.models import SkinslinkItem, SkinslinkState
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.orders_factory import make_item_and_rate, make_user_with_link

ACTIVE = {"skinslink_enabled": True, "skinslink_api_key": "k", "skinslink_secret": "s", "skins_buy_enabled": True, "waxpeer_api_key": "test-key-not-real"}


@pytest.fixture(autouse=True)
def _active(monkeypatch: pytest.MonkeyPatch) -> None:
    s = get_settings().model_copy(update=ACTIVE)
    monkeypatch.setattr("csmarket.modules.orders.routes.get_settings", lambda: s)  # the route's settings dependency: adapt to the suite's pattern


async def _seed(db: AsyncSession, prices: list[int]) -> tuple[str, str]:
    item, _ = await make_item_and_rate(db)
    db.add_all([SkinslinkItem(id=f"s{i}", market_hash_name=item.market_hash_name, phase=item.phase, price_units=p, skin_item_id=item.id) for i, p in enumerate(prices)])
    db.add(SkinslinkState(id=1, mirror_synced_at=datetime.now(UTC), cursor="c"))
    await db.commit()
    return item.slug, item.id


async def test_a_skinslink_offer_opens_a_skinslink_order(integration_client: AsyncClient, db_session: AsyncSession, shown_price) -> None:  # noqa: ANN001 -- the suite's helper that prices an offer the way the panel does
    slug, item_id = await _seed(db_session, [9_000])
    headers = await make_user_with_link(integration_client, db_session)
    r = await integration_client.post("/api/v1/orders", json={"slug": slug, "listing_id": "sl:s0", "price_uzs": await shown_price(item_id, 9_000)}, headers=headers)
    assert r.status_code == 201, r.text
    order = await db_session.scalar(select(Order).where(Order.number == r.json()["number"]))
    assert order is not None and (order.source, order.offer_id, order.listing_id, order.cost_units) == ("skinslink", "sl:s0", None, 9_000)


async def test_a_bare_integer_is_a_waxpeer_offer(integration_client: AsyncClient, db_session: AsyncSession, waxpeer_fake, shown_price) -> None:  # noqa: ANN001
    slug, item_id = await _seed(db_session, [])
    waxpeer_fake.list(item_id_=4242, price_units=12_345)  # the suite's fake listing helper
    headers = await make_user_with_link(integration_client, db_session)
    r = await integration_client.post("/api/v1/orders", json={"slug": slug, "listing_id": 4242, "price_uzs": await shown_price(item_id, 12_345)}, headers=headers)
    assert r.status_code == 201, r.text
    order = await db_session.scalar(select(Order).where(Order.number == r.json()["number"]))
    assert order is not None and (order.source, order.offer_id, order.listing_id) == ("waxpeer", "wx:4242", 4242)


async def test_next_offer_crosses_sources(integration_client: AsyncClient, db_session: AsyncSession, shown_price) -> None:  # noqa: ANN001
    slug, item_id = await _seed(db_session, [9_000])
    headers = await make_user_with_link(integration_client, db_session)
    # The buyer chose a Waxpeer offer that is gone; the cheapest live one is Skinslink's, far above the shown price.
    r = await integration_client.post("/api/v1/orders", json={"slug": slug, "listing_id": "wx:999999", "price_uzs": 1000}, headers=headers)
    assert r.status_code == 409 and r.json()["code"] == "offer_gone"
    assert r.json()["next_offer"]["listing_id"] == "sl:s0"


async def test_a_bad_offer_id_is_422(integration_client: AsyncClient, db_session: AsyncSession) -> None:
    slug, _ = await _seed(db_session, [])
    headers = await make_user_with_link(integration_client, db_session)
    r = await integration_client.post("/api/v1/orders", json={"slug": slug, "listing_id": "ebay:1", "price_uzs": 1000}, headers=headers)
    assert r.status_code == 422
```

Read `test_orders_checkout.py` first and reuse its fixtures for the fake Waxpeer listings and the price the panel shows (names above are placeholders for the suite's real helpers — use theirs). Update its existing assertions from `listing_id == 4242` to `"wx:4242"` where they read the response, and keep the request bodies as integers in at least one test (the compatibility path).

- [ ] **Step 2: Run them**

Run: `cd apps/api && uv run pytest tests/integration/test_orders_checkout_sources.py -q`
Expected: FAIL — 422 on `"sl:s0"` (`listing_id` is an int field).

- [ ] **Step 3: Implement**

`orders/schemas.py`:

```python
    #: The offer picked on the item page: ``wx:<id>`` / ``sl:<id>``; a bare integer reads as Waxpeer's (one release).
    listing_id: Annotated[int | str, Field(union_mode="left_to_right")]

    @field_validator("listing_id")
    @classmethod
    def _offer_id(cls, v: int | str) -> str:
        try:
            source, raw = parse_offer_id(v)
        except ValueError as exc:
            raise ValueError("not an offer id") from exc
        return offer_id_of(source, raw)
```

(`listing_id` is then always the normalised string inside the app.)

`orders/checkout.py`: imports `Offer, from_listing, merge_offers, offer_id_of` from `skins.api` and `offers_for` from `skinslink.api`; `_Priced = tuple[Offer, tuple[Decimal, Decimal]]`; in `create_order`, read `extra = await offers_for(db, q.snap.id, settings=settings, now=now())` inside `_read` (add it to `_Quoted` as `extra: list[Offer]`), then after the rollback and the Waxpeer read: `offers = merge_offers([from_listing(r) for r in rows], q.extra)`; `_choose` compares `p[0].offer_id == body.listing_id`; `next_offer={"listing_id": cheapest[0].offer_id, …}`; `_build(... source=row.source, offer_id=row.offer_id, listing_id=row.listing_id, cost_units=row.price_units)`; the `substituted=` log reads `row.offer_id != body.listing_id`.

`docs/api/README.md`: update the `POST /orders` paragraph and the 409 shapes.

- [ ] **Step 4: Run tests and gates**

Run: `cd apps/api && uv run pytest tests/integration/test_orders_checkout.py tests/integration/test_orders_checkout_sources.py tests/integration/test_orders_pay.py -q && cd ../.. && make lint typecheck && make gen-api`
Expected: PASS; clean; schema regenerated.

- [ ] **Step 5: Commit**

```bash
git add apps/api docs/api packages/api-client
git commit -m "feat(api/orders): checkout takes an offer of either source; the next offer crosses sources"
```

---

### Task 8: Buying from Skinslink in the worker

**Files:**

- Create: `apps/api/src/csmarket/modules/orders/skinslink_buying.py`
- Modify: `apps/api/src/csmarket/modules/orders/buying.py:106-136` (`_claim`), `:139-172` (`drain_paid` routing), `orders/buy_lease.py:40-62` (`take_lease(..., source)`), `orders/sweeps.py` (`_due` and `reconcile` consider only Waxpeer orders: `Order.source == "waxpeer"`)
- Modify: `apps/api/src/csmarket/modules/skinslink/api.py` (`SkinslinkPurchase`, `client_for`), `core/metrics.py` (`OrderBuyOutcome` unchanged; the counter is shared)
- Test: `apps/api/tests/integration/test_orders_skinslink_buying.py`, `apps/api/tests/integration/fake_skinslink_client.py`

**Interfaces:**

- `_claim` creates, per claimed order, a `SkinTrade` (source `waxpeer`, as today) **or** a `SkinslinkPurchase(order_id, asset_id=<raw id of offer_id>, paid_units=order.cost_units, status="new", buy_pending=True)`.
- `take_lease(db, order_id, *, source: str = "waxpeer")`: the `pending` EXISTS is on `skin_trades` for `waxpeer`, on `skinslink_purchases` for `skinslink`.
- `drain_paid` reads each claimed order's `source` (returned by `_claim` as `list[tuple[str, str]]`) and calls `attempt_buy` (Waxpeer) or `attempt_skinslink_buy(db, sl_client, order_id=…, settings=…)`; the Skinslink client is `client_for(settings, timeout_seconds=settings.skinslink_buy_timeout_seconds)`, built once per batch when a Skinslink order was claimed.
- `attempt_skinslink_buy(db, client, *, order_id, settings) -> str` outcomes: `bought` (status `pending`/`active`), `adopted` (repeat answered with the stored purchase), `sold_out`, `low_balance`, `invalid_link`, `forbidden`, `rate_limited`, `unconfirmed`, `lookup_later`, `nothing_to_do`. Logic:
  1. `take_lease(db, order_id, source="skinslink")`; `None` → `nothing_to_do`.
  2. Read order + purchase (`status == "buying"`, `buy_pending`); parse the trade link (bad → `refund(..., "invalid_trade_link")`).
  3. `purchase = await client.purchase(asset_id=…, partner=…, token=…, merchant_tx_id=order.id, max_price_usd=Decimal(paid_units)/1000)` — the ceiling (`paid_units × (1 + order_substitute_ceiling)`) is **our** substitute room; `max_price` to Skinslink is the chosen offer's own price (plus the ceiling only on the substitute attempt).
  4. Answer `status in ("new","pending","active","hold","completed")` → `record_purchase(db, snap, purchase)` (`purchase_id`, `status`, `offer_id`, `amount_units`, `buy_pending=False`) → `bought`; `active` with an offer id also applies the status (Task 9's `apply_report`) so the order goes `trade_sent` at once.
  5. Answer `status == "failed"` with `fail_reason` in `{"item_sold","item_not_available","price_changed","item_specified_price_not_found"}` → one substitute: the cheapest offer of the same `skin_item_id` from `merge_offers(skinslink offers_for(...), waxpeer listings_for(...))` within `ceiling`, not the one just tried; a **Skinslink** substitute → loop once more (new `merchant_tx_id = f"{order.id}:2"`, store it on the purchase as `merchant_tx_id`); a **Waxpeer** substitute → `switch_to_waxpeer(db, snap, listing)` creates a `SkinTrade(buy_pending=True)`, sets `order.source="waxpeer"`, `offer_id`, `listing_id`, deletes the purchase row, and returns `lookup_later` (the Waxpeer path buys it on the next tick); nothing → `refund(..., "sold_out")`.
  6. `fail_reason == "insufficient_balance"` → `refund(..., "source_low_balance")`; `duplicate_purchase` → treat as a repeat: `purchase_status(merchant_tx_id=…)` and adopt.
  7. `SkinslinkError` with `.code in LINK_ERROR_CODES` → `refund(..., "invalid_trade_link")`; `.status == 409` → `purchase_status` and adopt; other 4xx → `refund(..., "sold_out")` after one substitute attempt as in 5.
  8. `SkinslinkForbiddenError` → `attention(db, snap, "source_forbidden", outcome="forbidden")`; `SkinslinkRateLimitedError` → `rate_limited`; `SkinslinkUnavailableError` → `unconfirmed` (mark `buy_unconfirmed_at`, keep `buy_pending=False`) — the Task 9 reconcile resolves it with `purchase_status(merchant_tx_id)` (the idempotent repeat).
  - Writes mirror `buy_writes.py` but on `SkinslinkPurchase`: implement `_locked`, `record_purchase`, `refund`, `attention`, `unconfirmed`, `switch_to_waxpeer` in `skinslink_buying.py` itself (they are small; `refund_to_balance` and `flag`-like attention writes are reused: attention on the purchase row sets `attention_reason`, calls `record_trade_attention`).
- `sweeps._due` adds `Order.source == "waxpeer"` (Skinslink orders are reconciled by Task 9's job).

- [ ] **Step 1: Write the fake and the failing tests**

```python
# apps/api/tests/integration/fake_skinslink_client.py
"""A scripted Skinslink purchase client for the worker tests."""

from __future__ import annotations

from collections import deque
from decimal import Decimal

from csmarket.modules.skinslink.api import Purchase


def purchase(status: str = "pending", **over: object) -> Purchase:
    base: dict[str, object] = {"id": 178, "merchant_tx_id": "o", "status": status, "offer_id": None, "fail_reason": None, "amount_usd": Decimal("12.345"), "asset_id": "a0", "hold_end_date": None}
    base.update(over)
    return Purchase(**base)  # type: ignore[arg-type]


class FakeSkinslinkClient:
    """``script``: answers (a Purchase) or exceptions, popped per ``purchase`` call; ``statuses`` by merchant_tx_id."""

    def __init__(self, *script: object, statuses: dict[str, Purchase | None] | None = None) -> None:
        self.script = deque(script)
        self.statuses = statuses or {}
        self.calls: list[dict[str, object]] = []

    async def purchase(self, *, asset_id: str, partner: int, token: str, merchant_tx_id: str, max_price_usd: Decimal) -> Purchase:
        self.calls.append({"asset_id": asset_id, "merchant_tx_id": merchant_tx_id, "max_price_usd": max_price_usd})
        nxt = self.script.popleft()
        if isinstance(nxt, BaseException):
            raise nxt
        assert isinstance(nxt, Purchase)
        return nxt

    async def purchase_status(self, *, merchant_tx_id: str) -> Purchase | None:
        return self.statuses.get(merchant_tx_id)
```

```python
# apps/api/tests/integration/test_orders_skinslink_buying.py
"""``orders.skinslink_buying.attempt_skinslink_buy``: one order, one purchase at Skinslink."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from csmarket.core.config import Settings, get_settings
from csmarket.modules.orders.models import Order, SkinTrade
from csmarket.modules.orders.skinslink_buying import attempt_skinslink_buy
from csmarket.modules.skinslink.api import SkinslinkError, SkinslinkForbiddenError, SkinslinkRateLimitedError, SkinslinkUnavailableError
from csmarket.modules.skinslink.models import SkinslinkItem, SkinslinkPurchase, SkinslinkState
from csmarket.modules.wallet.api import user_balance
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.fake_skinslink_client import FakeSkinslinkClient, purchase
from tests.integration.orders_factory import make_item_and_rate, make_order, make_user_with_link

PRICE = Decimal(171_800)
COST = 12_345


@pytest.fixture
def settings() -> Settings:
    return get_settings().model_copy(update={"skinslink_enabled": True, "skinslink_api_key": "k", "skinslink_secret": "s"})


async def _buying(db: AsyncSession, *, mirror: list[tuple[str, int]] = (("a0", COST),), **over: object) -> Order:
    item, _ = await make_item_and_rate(db)
    user = await make_user_with_link(db)  # the factory's user with a saved fake link; adapt to its real signature
    order = await make_order(db, user=user, status="buying", paid_with="wallet", paid_at=datetime.now(UTC), source="skinslink", offer_id="sl:a0", listing_id=None, cost_units=COST, price_uzs=PRICE, skin_item_id=item.id, **over)
    db.add_all([SkinslinkItem(id=i, market_hash_name=item.market_hash_name, phase=item.phase, price_units=p, skin_item_id=item.id) for i, p in mirror])
    db.add(SkinslinkState(id=1, mirror_synced_at=datetime.now(UTC), cursor="c"))
    db.add(SkinslinkPurchase(order_id=order.id, asset_id="a0", paid_units=COST, status="new", buy_pending=True))
    await db.commit()
    return order


async def _purchase(db: AsyncSession, order: Order) -> SkinslinkPurchase:
    p = await db.scalar(select(SkinslinkPurchase).where(SkinslinkPurchase.order_id == order.id).execution_options(populate_existing=True))
    assert p is not None
    return p


async def test_success_records_the_purchase_and_pays_at_most_the_cost(db_session: AsyncSession, settings: Settings) -> None:
    order = await _buying(db_session)
    fake = FakeSkinslinkClient(purchase("pending"))
    assert await attempt_skinslink_buy(db_session, fake, order_id=order.id, settings=settings) == "bought"
    assert fake.calls[0]["merchant_tx_id"] == order.id and fake.calls[0]["max_price_usd"] == Decimal("12.345")
    p = await _purchase(db_session, order)
    assert (p.purchase_id, p.status, p.buy_pending) == (178, "pending", False)


async def test_active_answer_moves_the_order_to_trade_sent(db_session: AsyncSession, settings: Settings) -> None:
    order = await _buying(db_session)
    fake = FakeSkinslinkClient(purchase("active", offer_id="6912345678"))
    await attempt_skinslink_buy(db_session, fake, order_id=order.id, settings=settings)
    await db_session.refresh(order)
    assert order.status == "trade_sent"


async def test_lost_answer_is_resolved_by_repeat(db_session: AsyncSession, settings: Settings) -> None:
    order = await _buying(db_session)
    fake = FakeSkinslinkClient(SkinslinkUnavailableError("timeout"), statuses={})
    assert await attempt_skinslink_buy(db_session, fake, order_id=order.id, settings=settings) == "unconfirmed"
    p = await _purchase(db_session, order)
    assert p.buy_unconfirmed_at is not None and p.buy_pending is False
    assert len(fake.calls) == 1  # nothing bought twice


async def test_item_sold_substitutes_once_then_refunds(db_session: AsyncSession, settings: Settings) -> None:
    order = await _buying(db_session, mirror=[("a0", COST), ("a1", COST + 100)])
    fake = FakeSkinslinkClient(purchase("failed", fail_reason="item_sold"), purchase("failed", fail_reason="item_sold"))
    assert await attempt_skinslink_buy(db_session, fake, order_id=order.id, settings=settings) == "sold_out"
    assert [c["asset_id"] for c in fake.calls] == ["a0", "a1"]
    assert fake.calls[1]["merchant_tx_id"] == f"{order.id}:2"
    await db_session.refresh(order)
    assert (order.status, order.failure_reason) == ("failed", "sold_out")
    assert await user_balance(db_session, order.user_id) == PRICE


async def test_a_waxpeer_substitute_hands_the_order_to_the_waxpeer_path(db_session: AsyncSession, settings: Settings, waxpeer_listing) -> None:  # noqa: ANN001 -- the suite's fake Waxpeer listing fixture (see test_orders_buying.py)
    order = await _buying(db_session, mirror=[("a0", COST)])
    waxpeer_listing(item_id=777, price_units=COST)
    fake = FakeSkinslinkClient(purchase("failed", fail_reason="item_sold"))
    assert await attempt_skinslink_buy(db_session, fake, order_id=order.id, settings=settings) == "lookup_later"
    await db_session.refresh(order)
    assert (order.source, order.offer_id, order.listing_id) == ("waxpeer", "wx:777", 777)
    assert await db_session.scalar(select(SkinTrade).where(SkinTrade.order_id == order.id)) is not None
    assert await db_session.scalar(select(SkinslinkPurchase).where(SkinslinkPurchase.order_id == order.id)) is None


@pytest.mark.parametrize(("answer", "reason"), [(purchase("failed", fail_reason="insufficient_balance"), "source_low_balance"), (SkinslinkError("x", status=400, code="trade_banned"), "invalid_trade_link")])
async def test_refund_reasons(db_session: AsyncSession, settings: Settings, answer: object, reason: str) -> None:
    order = await _buying(db_session)
    await attempt_skinslink_buy(db_session, FakeSkinslinkClient(answer), order_id=order.id, settings=settings)
    await db_session.refresh(order)
    assert (order.status, order.failure_reason) == ("failed", reason)


async def test_forbidden_is_attention_and_rate_limit_waits(db_session: AsyncSession, settings: Settings) -> None:
    order = await _buying(db_session)
    assert await attempt_skinslink_buy(db_session, FakeSkinslinkClient(SkinslinkForbiddenError("x", status=403)), order_id=order.id, settings=settings) == "forbidden"
    assert (await _purchase(db_session, order)).attention_reason == "source_forbidden"
    other = await _buying(db_session)
    assert await attempt_skinslink_buy(db_session, FakeSkinslinkClient(SkinslinkRateLimitedError("x")), order_id=other.id, settings=settings) == "rate_limited"
    assert (await _purchase(db_session, other)).buy_pending is True


async def test_duplicate_adopts_the_stored_purchase(db_session: AsyncSession, settings: Settings) -> None:
    order = await _buying(db_session)
    fake = FakeSkinslinkClient(SkinslinkError("dup", status=409), statuses={order.id: purchase("active", offer_id="1")})
    assert await attempt_skinslink_buy(db_session, fake, order_id=order.id, settings=settings) == "adopted"
    assert (await _purchase(db_session, order)).purchase_id == 178


async def test_a_second_attempt_under_the_lease_does_nothing(db_session: AsyncSession, settings: Settings) -> None:
    order = await _buying(db_session)
    fake = FakeSkinslinkClient(SkinslinkRateLimitedError("x"))
    await attempt_skinslink_buy(db_session, fake, order_id=order.id, settings=settings)
    assert await attempt_skinslink_buy(db_session, fake, order_id=order.id, settings=settings) == "nothing_to_do"
```

Also extend `test_orders_buying_drain.py`: a paid Skinslink order claimed by `drain_paid` gets a `SkinslinkPurchase` row (not a `SkinTrade`), and `drain_paid(db, skinslink_client=fake)` buys it (add the keyword `skinslink_client: SkinslinkPurchaseClient | None = None` to `drain_paid`, where `SkinslinkPurchaseClient` is a small `Protocol` with `purchase` and `purchase_status`, defined in `skinslink/client.py` and exported).

- [ ] **Step 2: Run them**

Run: `cd apps/api && uv run pytest tests/integration/test_orders_skinslink_buying.py -q`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement**

`buy_lease.take_lease(db, order_id, *, source="waxpeer")`:

```python
    pending = (
        select(SkinTrade.order_id).where(SkinTrade.order_id == Order.id, SkinTrade.buy_pending.is_(True)).exists()
        if source == "waxpeer"
        else select(SkinslinkPurchase.order_id).where(SkinslinkPurchase.order_id == Order.id, SkinslinkPurchase.buy_pending.is_(True)).exists()
    )
```

(import `SkinslinkPurchase` from `csmarket.modules.skinslink.api`.)

`buying._claim` returns `list[tuple[str, str]]` (`order.id, order.source`) and adds the right row:

```python
        if order.source == "skinslink":
            _, asset_id = parse_offer_id(order.offer_id or "")
            db.add(SkinslinkPurchase(order_id=order.id, asset_id=asset_id, paid_units=order.cost_units, status="new", buy_pending=True))
        else:
            db.add(SkinTrade(order_id=order.id, project_id=order.id, listing_id=order.listing_id or 0, paid_units=order.cost_units, buy_pending=True, seller={}))
```

`drain_paid` builds `sl_client = skinslink_client or client_for(settings, timeout_seconds=settings.skinslink_buy_timeout_seconds)` lazily and dispatches by source.

`orders/skinslink_buying.py`: `attempt_skinslink_buy` with the lease, `asyncio.timeout_at` budget and the outcome table above; a `PurchaseSnapshot(BaseModel, frozen)` (`order_id, number, skin_item_id, asset_id, paid_units, unconfirmed`); writes lock order then purchase `FOR UPDATE` (ruling K) and re-check `status == "buying" and buy_pending`; the substitute search: `extra = await offers_for(db, snap.skin_item_id, settings=settings, now=now())`, `rows, _ = await listings_for(item_view, client=search_client(), redis=get_redis(), budget_per_minute=listings_budget(settings))` (the item view is read from `skin_items` by id), `merge_offers(...)`, first offer with `price_units <= ceiling` and `offer_id != tried`.

`sweeps._due`: `.where(Order.source == "waxpeer")`.

Log events: `orders.skinslink_buy` (number, outcome), `orders.skinslink_buy.refused` (number, code), never the link.

- [ ] **Step 4: Run tests and gates**

Run: `cd apps/api && uv run pytest tests/integration/test_orders_skinslink_buying.py tests/integration/test_orders_buying.py tests/integration/test_orders_buying_drain.py tests/integration/test_orders_buying_races.py tests/integration/test_orders_sweeps.py -q && cd ../.. && make lint typecheck`
Expected: PASS; clean.

- [ ] **Step 5: Commit**

```bash
git add apps/api/src apps/api/tests
git commit -m "feat(api/orders): buy from Skinslink — idempotent on our order id, one substitute of either source, refunds and attention as Waxpeer's"
```

---

### Task 9: Webhook, checks queue, status application, reconcile

**Files:**

- Create: `apps/api/src/csmarket/modules/skinslink/webhook.py`, `skinslink/routes.py`, `skinslink/checks.py`
- Create: `apps/api/src/csmarket/modules/orders/skinslink_status.py`
- Create: `apps/scheduler/src/csmarket_scheduler/jobs/skinslink_reconcile.py`
- Modify: `apps/api/src/csmarket/api/v1/router.py` (mount `skinslink.routes.router`), `apps/api/src/csmarket/bootstrap.py:126-152` (exempt `skinslink_webhook`), `apps/worker/src/csmarket_worker/consumer.py` (`Queue(name="skinslink", channel=SKINSLINK_CHANNEL, drain=_drain_skinslink_checks, concurrency=1)`), `apps/scheduler/src/csmarket_scheduler/main.py`, `orders/trade_view.py` (`skin_trade_out(order, trade, purchase=None)`), `orders/service.py` / `orders/routes.py` (load the purchase for a Skinslink order), `orders/api.py`, `skinslink/api.py`, `orders/letters.py:36-43` (`enqueue_trade_sent(db, order, trade=None, *, send_until=None)`)
- Test: `apps/api/tests/integration/test_skinslink_webhook.py`, `test_skinslink_status.py`, `apps/scheduler/tests/test_skinslink_reconcile_job.py`, update `apps/api/tests/unit/test_orders_trade_view.py` if present

**Interfaces:**

- `webhook.verify(body: Mapping[str, Any], *, secret: str) -> int | None`: the id (`purchase_id`, else `trade_id`) when `sign == base64(sha256(str(id) + secret))` (`hmac.compare_digest`), else `None`.
- `checks.enqueue_check(db, purchase_id: int) -> None` inserts `SkinslinkCheck` and `pg_notify(SKINSLINK_CHANNEL, str(purchase_id))` in the caller's transaction; `checks.claim_checks(db, *, limit=20) -> list[int]` (`FOR UPDATE SKIP LOCKED`, sets `claimed_at`, deletes claimed rows at the end of the drain — a check is one-shot; a failed poll is retried by the reconcile job, not by the row).
- Route `POST /api/v1/skinslink/webhook` (`routes.py`, router prefix `/skinslink`): 404 unless `settings.skinslink_active`; reads the raw JSON; `verify` → 403 on failure; a body with `trade_id` (deposit) → 200 `{"ok": true}` and nothing else; with `purchase_id` → `enqueue_check` + 200. Never parses `status`. On the exempt list in `bootstrap`.
- `orders/skinslink_status.py`:
  - `async def apply_report(db, *, order: Order, purchase: SkinslinkPurchase, report: Purchase) -> str` (caller holds both `FOR UPDATE`): mirror `status`, `offer_id`, `fail_reason`, `amount_units`, `hold_end_date`, `last_polled_at`; then by `report.status`: `active` with `offer_id` → `trade_sent` (+ `enqueue_trade_sent`, nudge); `hold` → unchanged (stay `trade_sent`); `completed` → `delivered` (nudge); `failed`/`canceled` on `buying|trade_sent` → `refund_to_balance(..., to_status="returned" if order.status == "trade_sent" else "failed", reason="not_accepted" if canceled/failed after an offer else mapped reason)`; `reverted` on a delivered order → attention `rolled_back` (money spent), on `trade_sent` → `returned` + refund; `new`/`pending` → unchanged. Returns `unchanged | trade_sent | delivered | returned | failed | rolled_back | held`.
  - `async def check_purchase(db, client, *, purchase_id: int | None = None, order_id: str | None = None) -> str`: finds the purchase row (by `purchase_id` or `order_id`), asks `client.purchase_status(merchant_tx_id=<stored merchant_tx_id or order_id>)`, locks order → purchase, applies. A `None` answer on an **unconfirmed** purchase older than `order_unconfirmed_minutes` → `refund(... "sold_out")` (Skinslink never created it); otherwise unchanged.
  - `async def drain_checks(db, *, client=None, limit=20) -> int` — the worker drain.
  - `async def reconcile_skinslink(db_factory, client, *, settings) -> int` — every open Skinslink purchase (`order.status in ("buying","trade_sent")`, `last_polled_at` older than 30 s, or `buy_unconfirmed_at` set) gets `check_purchase`; `buy_pending` ones get `attempt_skinslink_buy` (lease decides).
- `trade_view.skin_trade_out(order, trade, purchase=None)`: for a Skinslink order, `state` from `purchase.status` (`new|pending` → `buying`; `active|hold` → `offer_sent`; `completed` → `accepted` — Skinslink items are released when completed, so also `released`? no: `accepted`; `failed|canceled|reverted` or order `failed|returned` → `failed`); `offer_url` from `purchase.offer_id`; `seller=None`, `release_date=None`, `send_until=None`; `reason_code` as today from `order.failure_reason` / attention (`_needs_support` reads the purchase's `attention_reason`/`resolved_at`).
- Scheduler job `skinslink.reconcile` every 30 s (`first_run_after(75)`), skipped unless `skinslink_active`.

- [ ] **Step 1: Write the failing tests**

```python
# apps/api/tests/integration/test_skinslink_webhook.py
"""The webhook: signature or 403; the body is never trusted — a check is queued instead."""

from __future__ import annotations

import base64
import hashlib

import pytest
from csmarket.core.config import get_settings
from csmarket.modules.skinslink.models import SkinslinkCheck
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

SECRET = "test-secret-not-real"
ACTIVE = {"skinslink_enabled": True, "skinslink_api_key": "k", "skinslink_secret": SECRET}


def _sign(id_: int) -> str:
    return base64.b64encode(hashlib.sha256((str(id_) + SECRET).encode()).digest()).decode()


@pytest.fixture
def active(monkeypatch: pytest.MonkeyPatch) -> None:
    s = get_settings().model_copy(update=ACTIVE)
    monkeypatch.setattr("csmarket.modules.skinslink.routes.get_settings", lambda: s)


async def test_disabled_is_404(integration_client: AsyncClient) -> None:
    r = await integration_client.post("/api/v1/skinslink/webhook", json={"purchase_id": 1, "sign": "x", "status": "completed"})
    assert r.status_code == 404


async def test_bad_signature_is_403_and_queues_nothing(integration_client: AsyncClient, db_session: AsyncSession, active: None) -> None:
    r = await integration_client.post("/api/v1/skinslink/webhook", json={"purchase_id": 178, "sign": "nope", "status": "completed"})
    assert r.status_code == 403
    assert await db_session.scalar(select(func.count()).select_from(SkinslinkCheck)) == 0


async def test_good_signature_queues_a_check_and_answers_200(integration_client: AsyncClient, db_session: AsyncSession, active: None) -> None:
    r = await integration_client.post("/api/v1/skinslink/webhook", json={"purchase_id": 178, "sign": _sign(178), "status": "completed", "merchant_tx_id": "o", "amount": 1, "amount_currency": "usd"})
    assert r.status_code == 200
    rows = (await db_session.scalars(select(SkinslinkCheck))).all()
    assert [c.purchase_id for c in rows] == [178]


async def test_webhook_body_is_not_trusted(integration_client: AsyncClient, db_session: AsyncSession, active: None, skinslink_order) -> None:  # noqa: ANN001 -- a fixture from test_skinslink_status: a trade_sent order with purchase_id 178
    order, _ = skinslink_order
    r = await integration_client.post("/api/v1/skinslink/webhook", json={"purchase_id": 178, "sign": _sign(178), "status": "completed", "merchant_tx_id": order.id})
    assert r.status_code == 200
    await db_session.refresh(order)
    assert order.status == "trade_sent"  # only the check (which asks Skinslink) may move it


async def test_deposit_webhook_is_accepted_and_ignored(integration_client: AsyncClient, db_session: AsyncSession, active: None) -> None:
    r = await integration_client.post("/api/v1/skinslink/webhook", json={"trade_id": 5, "sign": _sign(5), "status": "completed"})
    assert r.status_code == 200
    assert await db_session.scalar(select(func.count()).select_from(SkinslinkCheck)) == 0


async def test_duplicates_are_harmless(integration_client: AsyncClient, db_session: AsyncSession, active: None) -> None:
    for _ in range(2):
        await integration_client.post("/api/v1/skinslink/webhook", json={"purchase_id": 9, "sign": _sign(9), "status": "active"})
    assert await db_session.scalar(select(func.count()).select_from(SkinslinkCheck)) == 2  # two one-shot checks; the drain makes both ask the API, which is idempotent
```

```python
# apps/api/tests/integration/test_skinslink_status.py
"""Skinslink statuses onto orders: trade_sent, delivered, refunds, rollback; the check drain."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from csmarket.core.config import get_settings
from csmarket.modules.orders.models import Order
from csmarket.modules.orders.skinslink_status import check_purchase, drain_checks
from csmarket.modules.orders.trade_view import skin_trade_out
from csmarket.modules.skinslink.checks import enqueue_check
from csmarket.modules.skinslink.models import SkinslinkPurchase
from csmarket.modules.wallet.api import user_balance
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.fake_skinslink_client import FakeSkinslinkClient, purchase
from tests.integration.orders_factory import make_item_and_rate, make_order, make_user_with_link

PRICE = Decimal(171_800)


@pytest.fixture
async def skinslink_order(db_session: AsyncSession) -> tuple[Order, SkinslinkPurchase]:
    item, _ = await make_item_and_rate(db_session)
    user = await make_user_with_link(db_session)
    order = await make_order(db_session, user=user, status="trade_sent", paid_with="wallet", paid_at=datetime.now(UTC), source="skinslink", offer_id="sl:a0", listing_id=None, cost_units=12_345, price_uzs=PRICE, skin_item_id=item.id)
    p = SkinslinkPurchase(order_id=order.id, asset_id="a0", paid_units=12_345, purchase_id=178, status="active", offer_id="6912345678", buy_pending=False)
    db_session.add(p)
    await db_session.commit()
    return order, p


async def _check(db: AsyncSession, order: Order, report: object) -> str:
    fake = FakeSkinslinkClient(statuses={order.id: report})  # type: ignore[dict-item]
    return await check_purchase(db, fake, order_id=order.id)


async def test_completed_delivers(db_session: AsyncSession, skinslink_order: tuple[Order, SkinslinkPurchase]) -> None:
    order, _ = skinslink_order
    assert await _check(db_session, order, purchase("completed", offer_id="6912345678")) == "delivered"
    await db_session.refresh(order)
    assert order.status == "delivered" and order.delivered_at is not None


async def test_hold_keeps_trade_sent(db_session: AsyncSession, skinslink_order: tuple[Order, SkinslinkPurchase]) -> None:
    order, _ = skinslink_order
    assert await _check(db_session, order, purchase("hold", offer_id="6912345678", hold_end_date="2026-10-13T00:00:00Z")) == "unchanged"
    await db_session.refresh(order)
    assert order.status == "trade_sent"


@pytest.mark.parametrize("status", ["failed", "canceled"])
async def test_declined_returns_the_money(db_session: AsyncSession, skinslink_order: tuple[Order, SkinslinkPurchase], status: str) -> None:
    order, _ = skinslink_order
    assert await _check(db_session, order, purchase(status, fail_reason=None)) == "returned"
    await db_session.refresh(order)
    assert (order.status, order.failure_reason, order.refunded_to) == ("returned", "not_accepted", "balance")
    assert await user_balance(db_session, order.user_id) == PRICE


async def test_reverted_after_delivery_is_attention_not_refund(db_session: AsyncSession, skinslink_order: tuple[Order, SkinslinkPurchase]) -> None:
    order, p = skinslink_order
    await _check(db_session, order, purchase("completed", offer_id="6912345678"))
    assert await _check(db_session, order, purchase("reverted", fail_reason="user_reverted")) == "rolled_back"
    await db_session.refresh(order)
    await db_session.refresh(p)
    assert order.status == "delivered" and p.attention_reason == "rolled_back"
    assert await user_balance(db_session, order.user_id) == Decimal(0)


async def test_the_buyer_view_of_a_skinslink_order(db_session: AsyncSession, skinslink_order: tuple[Order, SkinslinkPurchase]) -> None:
    order, p = skinslink_order
    view = skin_trade_out(order, None, purchase=p)
    assert view is not None and view.state == "offer_sent" and view.offer_url == "https://steamcommunity.com/tradeoffer/6912345678/"
    assert view.seller is None


async def test_drain_checks_asks_skinslink_and_applies(db_session: AsyncSession, skinslink_order: tuple[Order, SkinslinkPurchase]) -> None:
    order, _ = skinslink_order
    await enqueue_check(db_session, 178)
    await db_session.commit()
    fake = FakeSkinslinkClient(statuses={order.id: purchase("completed", offer_id="6912345678")})
    assert await drain_checks(db_session, client=fake) == 1
    await db_session.refresh(order)
    assert order.status == "delivered"
    assert await drain_checks(db_session, client=fake) == 0  # one-shot rows are gone


async def test_an_unconfirmed_buy_skinslink_never_saw_is_refunded(db_session: AsyncSession) -> None:
    item, _ = await make_item_and_rate(db_session)
    user = await make_user_with_link(db_session)
    order = await make_order(db_session, user=user, status="buying", paid_with="wallet", paid_at=datetime.now(UTC), source="skinslink", offer_id="sl:a0", listing_id=None, cost_units=12_345, price_uzs=PRICE, skin_item_id=item.id)
    db_session.add(SkinslinkPurchase(order_id=order.id, asset_id="a0", paid_units=12_345, status="new", buy_pending=False, buy_unconfirmed_at=datetime.now(UTC) - timedelta(minutes=get_settings().order_unconfirmed_minutes + 1)))
    await db_session.commit()
    assert await check_purchase(db_session, FakeSkinslinkClient(statuses={}), order_id=order.id) == "failed"
    await db_session.refresh(order)
    assert (order.status, order.failure_reason) == ("failed", "sold_out")
```

Scheduler test: `run()` skipped when inactive; with a scripted `reconcile_skinslink` raising, `run()` does not raise.

- [ ] **Step 2: Run them**

Run: `cd apps/api && uv run pytest tests/integration/test_skinslink_webhook.py tests/integration/test_skinslink_status.py -q`
Expected: FAIL — modules missing / 404 for every webhook call.

- [ ] **Step 3: Implement**

`skinslink/webhook.py`:

```python
def verify(body: Mapping[str, Any], *, secret: str) -> int | None:  # Any: the webhook's JSON
    """The purchase (or deposit) id the signature vouches for, or ``None``."""
    raw = body.get("purchase_id", body.get("trade_id"))
    sign = body.get("sign")
    if not isinstance(raw, int) or isinstance(raw, bool) or not isinstance(sign, str) or not secret:
        return None
    expected = base64.b64encode(hashlib.sha256((str(raw) + secret).encode()).digest()).decode()
    return raw if hmac.compare_digest(expected, sign) else None
```

`skinslink/routes.py`: `router = APIRouter(prefix="/skinslink", tags=["skinslink"])`; `@router.post("/webhook", include_in_schema=False)` `async def skinslink_webhook(request: Request, db: Db) -> dict[str, bool]`: `settings = get_settings()`; `if not settings.skinslink_active: raise NotFoundError(...)` (use the project's 404 error class); `body = await request.json()` inside `try` (bad JSON → 400); `pid = verify(body, secret=settings.skinslink_secret)`; `None` → `raise ForbiddenError("bad signature")`; `if "purchase_id" in body: await enqueue_check(db, pid); await db.commit()`; log `skinslink.webhook` with `kind=purchase|deposit` only; return `{"ok": True}`. Mount in `api/v1/router.py`; add `skinslink_webhook` to the exempt list in `bootstrap.py` with a comment ("Skinslink: `sign = sha256(id + secret)`; the body is not trusted, a check is queued").

`skinslink/checks.py` as in Interfaces (`SKINSLINK_CHANNEL` lives in `models.py`, exported by `api.py`).

`orders/skinslink_status.py` as in Interfaces; reuse `fsm.move`, `refund_to_balance`, `realtime.api.nudge`, `letters.enqueue_trade_sent(db, order, send_until=None)` (generalise the letter helper: it reads `trade.send_until` today — make `trade` optional and take `send_until` as a keyword), `record_trade_attention("rolled_back")`.

`trade_view.skin_trade_out(order, trade, purchase=None)`; `orders/service.py::order_out` (and the admin detail) load the purchase for `order.source == "skinslink"` (one extra `select` only for those orders; the list endpoint batches by `order_id IN (...)`).

Worker: `_drain_skinslink_checks(db) -> int: return await drain_checks(db)` (import from `orders.api`); the queue entry. Scheduler job per Interfaces.

`orders/api.py` exports `drain_checks`, `reconcile_skinslink`, `attempt_skinslink_buy`, `check_purchase`.

- [ ] **Step 4: Run tests and gates**

Run: `cd apps/api && uv run pytest tests/integration/test_skinslink_webhook.py tests/integration/test_skinslink_status.py tests/integration/test_orders_read.py tests/integration/test_orders_trades.py tests/unit -q -k "trade_view or skinslink or orders" && cd ../scheduler && uv run pytest tests -q -k skinslink && cd ../worker && uv run pytest tests -q && cd ../.. && make lint typecheck`
Expected: PASS; clean.

- [ ] **Step 5: Commit**

```bash
git add apps/api apps/worker apps/scheduler
git commit -m "feat(api/skinslink): the status webhook queues a check; statuses are read from the API and applied to orders"
```

---

### Task 10: Storefront and admin take the string offer id

**Files:**

- Modify: `packages/utils/src/skins/query.ts:88,99` (`listing_id: string`), `apps/web/src/lib/orders.ts:76,94,168-169`, `apps/web/src/components/skins/SkinBuyForm.tsx` (`listingId` state type, `orderKeyFor(..., bought.listing_id, ...)` — check `mintOrderKey`/`orderKeyFor` signatures in `apps/web/src/lib/order-key.ts` or wherever they live), `SkinListings.tsx`, `SkinOffers.tsx`, their tests, `apps/admin/src/features/orders/api.ts:41`, `fixtures.ts:45`, the admin order detail component (show `source` as a neutral label «Источник: Waxpeer / Skinslink» — admins may see it)
- Test: existing Vitest suites (ids become strings in fixtures), `apps/web/src/lib/orders.test.ts` for `next_offer` parsing with `"sl:…"`

**Interfaces:**

- Consumes: the regenerated `packages/api-client` (Task 5/7) where `listing_id: string`.
- Admin `AdminOrderFull` / `AdminTradeOut` (API, Task 11) gain `source: "waxpeer" | "skinslink"`; the admin shows it in the order header. This task updates the TS types to match once Task 11 lands — if executed before Task 11, type `source` as optional.

- [ ] **Step 1: Write the failing tests**

In `apps/web/src/lib/orders.test.ts` (create if absent) add:

```ts
import { describe, expect, it } from "vitest";

import { nextOfferOf } from "./orders"; // the helper at orders.ts:168 — export it if it is not

describe("offer ids", () => {
  it("reads a Skinslink next offer", () => {
    expect(nextOfferOf({ listing_id: "sl:38029384123", price_uzs: "171800" })).toEqual({
      listing_id: "sl:38029384123",
      price_uzs: "171800",
    });
  });
  it("ignores a malformed next offer", () => {
    expect(nextOfferOf({ listing_id: 42, price_uzs: "1" })).toBeNull();
  });
});
```

Update `SkinListings.test.tsx` / `SkinBuyForm.test.tsx` / `SkinOffers.test.tsx` fixtures: `listing_id: "wx:4242"` etc.; one `SkinBuyForm` test posts an order and asserts the body carries `listing_id: "sl:a0"` unchanged (no `Number()`).

- [ ] **Step 2: Run them**

Run: `cd apps/web && pnpm exec vitest run src/lib/orders.test.ts src/components/skins 2>&1 | tail -5`
Expected: FAIL — type and value mismatches (`number` vs `string`).

- [ ] **Step 3: Implement**

Change the types to `string`; in `orders.ts:168` the guard becomes `typeof o.listing_id === "string"`; the buy form's request body sends the string. Admin: `listing_id: string | null` (Skinslink orders have none) and `source`. Regenerate nothing here (the client was regenerated in Tasks 5/7).

- [ ] **Step 4: Run gates**

Run: `make lint typecheck && make test-ts`
Expected: clean; all green.

- [ ] **Step 5: Commit**

```bash
git add packages/utils apps/web apps/admin
git commit -m "feat(web/skins): offers carry a string id of either source; admin shows the order's source"
```

---

### Task 11: Admin, balance, metrics, alerts

**Files:**

- Create: `apps/api/src/csmarket/modules/skinslink/balance.py`, `apps/scheduler/src/csmarket_scheduler/jobs/skinslink_balance.py`
- Modify: `apps/api/src/csmarket/modules/orders/dashboard.py:60-80,150-178` (`skinslink: SourceBalance`), `admin/dashboard_schemas.py:58-95` (`skinslink: SkinslinkOut {available_usd, hold_usd, read_at}`), `admin/orders_schemas.py:100-160` (`source`, `listing_id: int | None`, `skinslink: AdminSkinslinkPurchaseOut | None` with `purchase_id, status, offer_id, fail_reason, amount_usd, hold_end_date, attention_reason`), the admin detail builder, `core/metrics.py` (gauges `csmarket_skinslink_balance_available_usd`, `csmarket_skinslink_balance_hold_usd`, `csmarket_skinslink_balance_read_timestamp_seconds`, `csmarket_skinslink_balance_threshold_usd`; `set_skinslink_balance(available, hold, threshold)`), `infra/prometheus/alerts/orders.yml` (three alerts), `apps/scheduler/src/csmarket_scheduler/main.py`, `docs/architecture/metrics.md`, `docs/architecture/cache-keys.md` (`skinslink:balance`)
- Test: `apps/api/tests/integration/test_skinslink_balance.py`, update `test_admin_orders.py` (detail shows `source`), the dashboard test
- Admin SPA: `apps/admin/src/features/dashboard/*` shows the Skinslink balance card beside Waxpeer's (label «Skinslink», two numbers: доступно / в холде); `features/orders/OrderDetail.tsx` shows the Skinslink block when present.

**Interfaces:**

- `balance.refresh_balance(redis, client, *, settings) -> Balance | None` — reads `GET /merchant/balance`, caches `{"available": str, "hold": str, "read_at": iso}` under Redis `skinslink:balance` (TTL 1 h), sets the gauges; a failure logs the type and returns `None` (the gauges keep their last value; the timestamp gauge does not move).
- `balance.cached_balance(redis) -> tuple[Decimal | None, Decimal | None, datetime | None]`.
- Job `skinslink.balance` every 5 minutes (`first_run_after(90)`), skipped unless active.
- Alerts (`infra/prometheus/alerts/orders.yml`, each with `runbook:` to `docs/runbooks/skinslink.md#…`):
  - `SkinslinkMirrorStale`: `time() - max(csmarket_skinslink_mirror_synced_timestamp_seconds{job="scheduler"}) > 600` for 5m, `severity: warn` — only meaningful when enabled: guard with `and on() (max(csmarket_skinslink_balance_threshold_usd) > 0)` or export a `csmarket_skinslink_enabled` gauge (1/0) from the balance job and `and on() max(csmarket_skinslink_enabled) == 1` — do the latter (gauge `csmarket_skinslink_enabled`, set every balance tick).
  - `SkinslinkBalanceLow`: `min(csmarket_skinslink_balance_available_usd) < min(csmarket_skinslink_balance_threshold_usd)` for 10m, page.
  - `SkinslinkBuyFailures`: `increase(csmarket_skinslink_calls_total{endpoint="purchase",outcome=~"refused|forbidden|unavailable"}[15m]) > 5` warn.

- [ ] **Step 1: Write the failing tests**

```python
# apps/api/tests/integration/test_skinslink_balance.py
from __future__ import annotations

from decimal import Decimal

from csmarket.core.config import get_settings
from csmarket.modules.skinslink.api import Balance
from csmarket.modules.skinslink.balance import cached_balance, refresh_balance
from prometheus_client import REGISTRY
from redis.asyncio import Redis


class _Client:
    def __init__(self, answer: Balance | Exception) -> None:
        self.answer = answer

    async def balance(self) -> Balance:
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


async def test_refresh_caches_and_exports(redis: Redis) -> None:
    settings = get_settings().model_copy(update={"skinslink_balance_alert_usd": Decimal(50)})
    out = await refresh_balance(redis, _Client(Balance(total=Decimal("12.5"), hold=Decimal(2), available=Decimal("10.5"))), settings=settings)  # type: ignore[arg-type]
    assert out is not None
    available, hold, read_at = await cached_balance(redis)
    assert (available, hold) == (Decimal("10.5"), Decimal(2)) and read_at is not None
    assert REGISTRY.get_sample_value("csmarket_skinslink_balance_available_usd") == 10.5
    assert REGISTRY.get_sample_value("csmarket_skinslink_balance_threshold_usd") == 50.0


async def test_a_failed_read_keeps_the_cache(redis: Redis) -> None:
    from csmarket.modules.skinslink.api import SkinslinkUnavailableError

    settings = get_settings()
    await refresh_balance(redis, _Client(Balance(total=Decimal(1), hold=Decimal(0), available=Decimal(1))), settings=settings)  # type: ignore[arg-type]
    assert await refresh_balance(redis, _Client(SkinslinkUnavailableError("x")), settings=settings) is None  # type: ignore[arg-type]
    available, _, _ = await cached_balance(redis)
    assert available == Decimal(1)
```

Admin: in `test_admin_orders.py`, the detail of a Skinslink order (reuse the `skinslink_order` fixture pattern) has `json["order"]["source"] == "skinslink"`, `json["order"]["listing_id"] is None`, `json["skinslink"]["purchase_id"] == 178`; a Waxpeer order has `source == "waxpeer"` and `json["skinslink"] is None`. Dashboard test: `json["skinslink"]["available_usd"]` present (`null` before any read).

- [ ] **Step 2: Run them**

Run: `cd apps/api && uv run pytest tests/integration/test_skinslink_balance.py tests/integration/test_admin_orders.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

Per Interfaces. Follow `orders/health.py::cache_balance` for the Redis shape and `orders/dashboard.py::WaxpeerBalance` for the dashboard field. Admin SPA: add the card and the block; fixtures updated; Vitest green.

Docs: `docs/architecture/metrics.md` (the new series), `docs/architecture/cache-keys.md` (`skinslink:balance`).

- [ ] **Step 4: Run gates**

Run: `cd apps/api && uv run pytest tests/integration/test_skinslink_balance.py tests/integration/test_admin_orders.py tests/integration -q -k "dashboard or admin_orders" && cd ../.. && make lint typecheck && make test-ts && make gen-api && docker run --rm -v "$PWD/infra/prometheus:/p:ro" --entrypoint promtool prom/prometheus:v3.12.0 check rules /p/alerts/orders.yml`
Expected: PASS; clean; rules valid.

- [ ] **Step 5: Commit**

```bash
git add apps packages docs infra
git commit -m "feat(api/skinslink): balance read, admin dashboard and order detail, metrics and alerts"
```

---

### Task 12: Documents

**Files:**

- Create: `docs/decisions/0010-skinslink-buy-source.md` (from `0000-template.md`), `docs/runbooks/skinslink.md`, `docs/architecture/sequence-diagrams/skinslink-buy.mmd`
- Modify: `apps/api/src/csmarket/modules/skinslink/README.md` (full), `apps/api/src/csmarket/modules/orders/README.md`, `apps/api/src/csmarket/modules/skins/README.md`, `docs/architecture/module-map.md` (row `skinslink`; the `skins → listings` row notes the merge; `orders` row notes the second source), `docs/security/pii-handling.md` (what Skinslink payloads carry and what we keep: never `steam_id`; `partner`/`token` only in request bodies), `docs/api/README.md` (webhook, `listing_id` prefix — already in Task 7, verify), `docs/superpowers/specs/2026-10-01-csmarket-design.md` (§2 and §17 point to the new spec), `AGENTS.md` (§0 status line; §11 no new carve-out: say the webhook enqueues only; §4 "A payment provider" row gains "a skin source: `modules/<source>/` with a client, a mirror or live read, a purchase record and a webhook, wired into `orders` by `source`"), `docs/tech-debt.md` (the one-release integer `listing_id` compatibility — remove after the next deploy)

- [ ] **Step 1: ADR-0010**

Context (the approved spec named Skinslink the sell side; the owner wants it as a buy source on 2026-10-06), decision (approach A: beside Waxpeer, `source` on the order, a mirror instead of live reads, a webhook that only enqueues), consequences (two sources to fund and watch; the sell side reuses the client and models later; the `supplier` ban → `source`), alternatives (B: one neutral trade model — deferred; C: fallback-only — rejected: the cheaper offers would never show).

- [ ] **Step 2: Runbook `docs/runbooks/skinslink.md`**

Sections: Credentials (where, rotation, never in chat), IP whitelist (`57.131.198.69`), Webhook URL, Enabling (`CSMARKET_SKINSLINK_ENABLED=on` → `up -d api worker scheduler`), Balance (how to top up; `#balance-low`), Mirror stale (`#mirror-stale`: check the scheduler log `skinslink.mirror.failed`, their status page, 403 = whitelist), Buy failures (`#buy-failures`), Disabling (what happens to in-flight Skinslink orders: the reconcile job still runs for them while the keys are present; removing the keys parks them for an admin).

- [ ] **Step 3: Sequence diagram**

`skinslink-buy.mmd`: buyer → web → api `POST /orders` (mirror read) → worker `drain_paid` → Skinslink `POST /merchant/purchase` → Skinslink webhook → api (verify, enqueue) → worker `drain_checks` → Skinslink `GET /merchant/purchase/status` → order `trade_sent` → `delivered`.

- [ ] **Step 4: The rest**

Module READMEs (what each owns, tables, jobs, settings, tests), module map, PII, spec pointers, AGENTS §0/§4, tech-debt entry.

- [ ] **Step 5: Gates and commit**

Run: `npx prettier --check . && make lint`
Expected: clean.

```bash
git add docs AGENTS.md apps/api/src/csmarket/modules/*/README.md
git commit -m "docs: ADR-0010 Skinslink as a buy source, runbook, module map, PII, spec pointers"
```

---

## Self-review

- **Spec coverage:** §3 mirror → Task 4; §4 prices/offers/ids → Tasks 5–6; §5 orders/buy/failures → Tasks 7–8; §6 webhook/status/reconcile → Task 9; §7 settings/admin/metrics/alerts → Tasks 1, 11; §8 tests → each task; §9 documents → Task 12; §10 rollout → runbook (Task 12). The spec's `skinslink_checks` queue, the `merchant_tx_id` repeat, the 10-minute staleness, the `wx:`/`sl:` ids and the one-release integer compatibility all have tasks.
- **Placeholders:** none; helper fixtures named in Tasks 7–8 (`shown_price`, `waxpeer_fake`, `waxpeer_listing`, `make_user_with_link`) are the suite's existing helpers — the implementer reads `test_orders_checkout.py` / `test_orders_buying.py` / `orders_factory.py` first and uses their real names.
- **Type consistency:** `Offer.offer_id: str`, `parse_offer_id -> (Source, str)`, `offers_for(db, skin_item_id, *, settings, now)`, `attempt_skinslink_buy(db, client, *, order_id, settings)`, `check_purchase(db, client, *, purchase_id=None, order_id=None)`, `apply_report(db, *, order, purchase, report)`, `take_lease(db, order_id, *, source)` are used with the same names across Tasks 5–9.
- **Review Focus:** each of the five lines names its test and task above.
