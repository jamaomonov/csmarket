# LIS-SKINS as a Buy Source — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show LIS-SKINS' instant-delivery lots beside Skinslink's, price every card from the cheapest source present, and buy from LIS-SKINS when the buyer picks one of its lots — with the money guards of the Skinslink path.

**Architecture:** A new module `modules/lisskins/` owns the Bearer HTTP client, the reader of the public export (streamed through `core.json_stream.ItemsScanner`, moved out of `skinslink` and generalised), the snapshot (`lisskins_offers` — the 10 cheapest instant lots per catalogue item — and `lisskins_state`), its roll-up onto `skin_items`, the checkout's live availability check (budget + breaker) and the balance read. `skins` gains the third source (`ls:` ids, tie order Waxpeer → Skinslink → LIS-SKINS, one Steam asset shown once) and an n-ary cost; `skins.source_prices` runs the snapshot apply and the sources' price tick. `orders` gets a shared `substitutes.py` (both non-Waxpeer buy paths), `purchase_rows.py`, and `lisskins_{status,writes,buying,reconcile}`; statuses are polled, 200 orders per `GET /market/info`. Everything is behind `CSMARKET_LISSKINS_ENABLED`.

**Tech Stack:** FastAPI, SQLAlchemy 2 async, Alembic, Pydantic v2, httpx + respx, APScheduler, Postgres queue (`FOR UPDATE SKIP LOCKED`), Redis, Vite admin (React 19, Vitest), Next.js storefront.

**Spec:** `docs/superpowers/specs/2026-10-07-lisskins-buy-source-design.md`. Precedent (same shape, read for context): `docs/superpowers/plans/2026-10-06-skinslink-buy-source.md` and the code it produced in `apps/api/src/csmarket/modules/skinslink/` and `apps/api/src/csmarket/modules/orders/skinslink_*.py`.

## Global Constraints

- The words `supplier` and `game_id` are banned under `apps/*/src` (`scripts/check-no-yupay.sh`): the source is `lisskins`; LIS-SKINS' return reason `rollback_supplier` is matched by the prefix `rollback_` and never spelled; the export's game field is never read.
- Never log PII: no `steam_id` (LIS-SKINS purchase answers carry the buyer's — the client never reads it), `partner`, `token`, trade link; LIS-SKINS error bodies are never logged (the `error` code only). `lisskins_api_key` joins the redaction list (`authorization` is already on it).
- One new advisory external call on the request path: `GET /market/check-availability` inside `POST /orders` — 4 s timeout, 100 calls/min for the whole API, a 120 s breaker; ADR-0012, an AGENTS §11 line, the latency alert comment.
- Money paths have tests for success, retryable failure and idempotent re-call; `lisskins`, `orders`, `skins`, `skinslink` keep ≥ 95 % line coverage each (`scripts/check-module-coverage.py`).
- Units: 1000 = $1 everywhere. LIS-SKINS prices are USD with two decimals → `× 1000`, half up. `max_price` sent to LIS-SKINS = `paid_units / 1000` rounded **down** to cents.
- Offer id on the wire: `ls:<1–20 digits>` (LIS-SKINS skin id). Ties at one price: Waxpeer, Skinslink, LIS-SKINS. One Steam asset listed by two sources is shown once, at the cheaper offer.
- Only lots with `delivery_type == 1` and `unlock_at` null are kept, offered, priced or bought.
- The scheduler container has 512 MB: the export (~855 MB, ~2.4 M lots) is never in memory whole; only the 10 cheapest lots per catalogue item are kept.
- `CSMARKET_LISSKINS_ENABLED=false` (the default) changes nothing: no snapshot ticks, no offers, no LIS-SKINS prices, no checkout call. The reconcile still runs while a key is set, so orders paid before a switch-off settle.
- Waxpeer buying is off in prod (`CSMARKET_WAXPEER_BUY_ENABLED=false`) but every cost, count, merge and substitute keeps including Waxpeer when it is on.
- The customer never sees a source name; `degraded` keeps meaning "Waxpeer answered from a fallback".
- Commits: Conventional Commits, scopes `api/lisskins`, `api/skins`, `api/orders`, `api/admin`, `scheduler`, `admin/orders`, `admin/dashboard`, `web/orders`, `infra`, `docs`; every commit ends with the trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` (or the session's model line).
- Before each commit: the task's tests, then `make lint typecheck`; `make gen-api` when a route or schema changes (commit `docs/api/openapi.json` + `packages/api-client`); prettier only from the repo root (`npx prettier --write <files>`), never from `apps/web`.

## Review Focus

1. A LIS-SKINS export that is cut off mid-array (a dropped connection, a CDN timeout) must leave yesterday's offers and prices exactly as they were — not wipe them, not half-apply — pinned in Task 4 (`test_a_truncated_export_changes_nothing`).
2. A Doppler-family lot whose name carries no phase must land on the catalogue row of its own phase (by `item_paint_index` against `skin_items.paint_index`), never on another phase's row and never priced as the phaseless name — pinned in Task 4 (`test_a_doppler_without_a_phase_maps_by_paint_index`).
3. Checkout of an `ls:` lot whose live price rose beyond the ±2 % tolerance must answer 409 `price_changed` with the new soʻm price, never bill the five-minute-old snapshot price — pinned in Task 6 (`test_a_dearer_live_price_is_price_changed_never_the_snapshot_price`).
4. A buy whose answer was lost must be settled by LIS-SKINS' own record: a repeat answered `custom_id_already_exists` adopts the stored purchase, and a purchase we hold a `purchase_id` for that `market/info` happens to omit is left alone — never refunded, never bought twice — pinned in Task 9 (`test_a_repeat_after_a_lost_answer_adopts_the_stored_purchase`) and Task 10 (`test_a_known_purchase_missing_from_info_is_left_alone`).
5. A trade rolled back (`return` with a `rollback_…` reason) days after LIS-SKINS reported `accepted` must open the `rolled_back` attention on the already-delivered order, never refund — which needs delivered orders polled through Steam's trade protection — pinned in Task 10 (`test_a_rollback_after_delivery_is_seen_by_the_protection_poll`).

---

### Task 1: Settings, redaction, coverage gate, module skeleton

**Files:**

- Modify: `apps/api/src/csmarket/core/config.py` (after `skinslink_balance_alert_usd`; the property after `skinslink_active`)
- Modify: `apps/api/src/csmarket/core/logging.py` (`REDACTED_KEYS`, after `"x-api-key"`)
- Modify: `.env.example` (after the Skinslink block), `infra/secrets-example/api.env` (after `CSMARKET_SKINSLINK_SECRET`)
- Modify: `scripts/check-module-coverage.py` (`MODULES`), `apps/api/tests/unit/test_check_module_coverage.py:14` (its own `MODULES`)
- Create: `apps/api/src/csmarket/modules/lisskins/__init__.py` (empty), `apps/api/src/csmarket/modules/lisskins/api.py`, `apps/api/src/csmarket/modules/lisskins/README.md`
- Test: `apps/api/tests/unit/test_lisskins_settings.py`

**Interfaces:**

- Produces: `Settings.lisskins_enabled: bool = False`, `lisskins_api_key: str = ""`, `lisskins_base_url: str = "https://api.lis-skins.com/v1"`, `lisskins_export_url: str = "https://lis-skins.com/market_export_json/api_csgo_full.json"`, `lisskins_stale_minutes: int = 20`, `lisskins_request_timeout_seconds: float = 10.0`, `lisskins_buy_timeout_seconds: float = 35.0`, `lisskins_check_timeout_seconds: float = 4.0`, `lisskins_balance_alert_usd: Decimal = 100`; `Settings.lisskins_active -> bool` (switch **and** key).

- [ ] **Step 1: Write the failing test**

```python
# apps/api/tests/unit/test_lisskins_settings.py
"""LIS-SKINS settings: off by default, active only with the switch and the key."""

from __future__ import annotations

from decimal import Decimal

import csmarket.modules.lisskins.api as lisskins_api
from csmarket.core.config import Settings
from csmarket.core.logging import REDACTED_KEYS


def _make(**kw: object) -> Settings:
    return Settings(_env_file=None, **kw)  # type: ignore[call-arg, arg-type]


def test_disabled_by_default() -> None:
    s = _make()
    assert s.lisskins_enabled is False
    assert s.lisskins_active is False
    assert s.lisskins_base_url == "https://api.lis-skins.com/v1"
    assert s.lisskins_export_url == (
        "https://lis-skins.com/market_export_json/api_csgo_full.json"
    )
    assert (s.lisskins_stale_minutes, s.lisskins_request_timeout_seconds) == (20, 10.0)
    assert (s.lisskins_buy_timeout_seconds, s.lisskins_check_timeout_seconds) == (35.0, 4.0)
    assert s.lisskins_balance_alert_usd == Decimal(100)


def test_active_needs_the_switch_and_the_key() -> None:
    assert _make(lisskins_enabled=True).lisskins_active is False
    assert _make(lisskins_api_key="k").lisskins_active is False
    assert _make(lisskins_enabled=True, lisskins_api_key="k").lisskins_active is True


def test_the_key_is_redacted() -> None:
    assert "lisskins_api_key" in REDACTED_KEYS


def test_the_module_has_a_public_interface() -> None:
    assert isinstance(lisskins_api.__all__, list)
```

- [ ] **Step 2: Run it**

Run: `cd apps/api && uv run pytest tests/unit/test_lisskins_settings.py -q`
Expected: FAIL — `ModuleNotFoundError: csmarket.modules.lisskins`.

- [ ] **Step 3: Add the settings, the redaction, the gate and the skeleton**

`core/config.py`, right after `skinslink_balance_alert_usd`:

```python
    # --- lisskins (third buy source; spec 2026-10-07) ---
    lisskins_enabled: bool = Field(
        default=False,
        description="Snapshot LIS-SKINS' instant lots, show them, buy from LIS-SKINS.",
    )
    lisskins_api_key: str = Field(default="", description="LIS-SKINS API key (Bearer).")
    lisskins_base_url: str = Field(default="https://api.lis-skins.com/v1")
    lisskins_export_url: str = Field(
        default="https://lis-skins.com/market_export_json/api_csgo_full.json",
        description="The public price export (no key; ~855 MB, streamed).",
    )
    lisskins_stale_minutes: int = Field(
        default=20, ge=1, description="A snapshot older than this offers and prices nothing."
    )
    lisskins_request_timeout_seconds: float = Field(default=10.0, gt=0)
    lisskins_buy_timeout_seconds: float = Field(default=35.0, gt=0)
    lisskins_check_timeout_seconds: float = Field(
        default=4.0, gt=0, description="The checkout's check-availability call (ADR-0012)."
    )
    lisskins_balance_alert_usd: Decimal = Field(default=Decimal(100))
```

and after the `skinslink_active` property:

```python
    @property
    def lisskins_active(self) -> bool:
        """LIS-SKINS is used: switched on with the key present."""
        return self.lisskins_enabled and bool(self.lisskins_api_key)
```

`core/logging.py`, in `REDACTED_KEYS` after `"x-api-key",`:

```python
        # LIS-SKINS (spec 2026-10-07): the key rides an ``Authorization: Bearer`` header.
        "lisskins_api_key",
```

`.env.example` (after the Skinslink block):

```
# LIS-SKINS — the third buy source (spec 2026-10-07). Off until the key is set.
CSMARKET_LISSKINS_ENABLED=false
CSMARKET_LISSKINS_API_KEY=
```

`infra/secrets-example/api.env` (after `CSMARKET_SKINSLINK_SECRET`):

```
# LIS-SKINS API key (docs/runbooks/lisskins.md). It answers only from the VPS IP.
CSMARKET_LISSKINS_ENABLED=false
CSMARKET_LISSKINS_API_KEY=CHANGE_ME_lisskins_api_key
```

`scripts/check-module-coverage.py` and `apps/api/tests/unit/test_check_module_coverage.py`, both:

```python
MODULES = (
    "orders",
    "payments",
    "wallet",
    "skins",
    "notifications",
    "realtime",
    "skinslink",
    "lisskins",
)
```

`modules/lisskins/api.py`:

```python
"""Public interface of the ``lisskins`` module — other modules import from here only."""

from __future__ import annotations

__all__: list[str] = []
```

`modules/lisskins/README.md`: a heading, one paragraph (owns: the LIS-SKINS client, the export reader, the snapshot of instant lots and its roll-up, the checkout availability check, purchase records, the balance read; does not own: pricing rules, orders — `orders` buys and applies statuses), a "Settings" table of the nine settings above. Task 13 completes it.

- [ ] **Step 4: Run the test and the gates**

Run: `cd apps/api && uv run pytest tests/unit/test_lisskins_settings.py tests/unit/test_check_module_coverage.py -q && cd ../.. && make lint typecheck`
Expected: PASS; lint (check-no-yupay included) and mypy clean.

- [ ] **Step 5: Commit**

```bash
git add apps/api/src/csmarket/core/config.py apps/api/src/csmarket/core/logging.py .env.example infra/secrets-example/api.env scripts/check-module-coverage.py apps/api/tests/unit/test_check_module_coverage.py apps/api/src/csmarket/modules/lisskins apps/api/tests/unit/test_lisskins_settings.py
git commit -m "feat(api/lisskins): settings, redaction and the coverage gate for the third buy source" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: The stream scanner generalised, the LIS-SKINS client and the export reader

Decision: `ItemsScanner` moves from `modules/skinslink/stream.py` to `core/json_stream.py` (two modules use it now; a module may not import another module's internals) and takes the success and cursor patterns as keyword arguments, whose defaults are Skinslink's — so Skinslink's call sites keep working unchanged apart from the import.

**Files:**

- Move: `apps/api/src/csmarket/modules/skinslink/stream.py` → `apps/api/src/csmarket/core/json_stream.py` (`git mv`), generalised
- Modify: `apps/api/src/csmarket/modules/skinslink/client.py:24` (import), `apps/api/tests/contract/test_skinslink_client.py` (import)
- Modify: `apps/api/src/csmarket/core/metrics.py` (one counter)
- Create: `apps/api/src/csmarket/modules/lisskins/values.py`, `client.py`, `export.py`; modify `lisskins/api.py`
- Test: `apps/api/tests/unit/test_json_stream.py`, `apps/api/tests/contract/test_lisskins_client.py`, `apps/api/tests/contract/test_lisskins_export.py`

**Interfaces:**

- Produces in `core/json_stream.py`: `ItemsScanner(*, success: re.Pattern[str] = SUCCESS_TRUE, cursor: re.Pattern[str] = LAST_UPDATE_AT)` with `feed(text) -> list[Any]`, `finish() -> str | None` (the cursor pattern's group 1), `total_pages`, `headless`; constants `SUCCESS_TRUE`, `LAST_UPDATE_AT`.
- Produces in `core/metrics.py`: `LisskinsEndpoint = Literal["export", "buy", "info", "check", "balance"]`, `LisskinsOutcome = Literal["ok", "refused", "forbidden", "rate_limited", "unavailable"]`, counter `csmarket_lisskins_calls_total{endpoint,outcome}`, `record_lisskins_call(endpoint, outcome) -> None` (never raises; unknown values → `other`).
- Produces in `lisskins/client.py` (re-exported by `api.py`):
  - errors: `LisskinsError(Exception)` with `.status: int`, `.code: str | None`, `.unavailable_ids: tuple[int, ...]`; `LisskinsForbiddenError(LisskinsError)` (401/403); `LisskinsUnavailableError(Exception)` (transport, 408/5xx, unreadable body, no key); `LisskinsRateLimitedError(LisskinsUnavailableError)` with `.retry_after: float | None`.
  - `@dataclass(frozen=True) PurchasedSkin(id: int, price_usd: Decimal | None, status: str, return_reason: str | None, error: str | None, offer_id: str | None, offer_expiry_at: str | None)`
  - `@dataclass(frozen=True) Purchase(purchase_id: int, custom_id: str | None, skins: tuple[PurchasedSkin, ...])` with property `skin -> PurchasedSkin` (the first).
  - `@dataclass(frozen=True) Balance(available: Decimal, locked: Decimal, protected: Decimal)`; `@dataclass(frozen=True) Availability(available: dict[int, Decimal], unavailable: frozenset[int])`.
  - Protocols `LisskinsBuyClient` (`buy`, `info`) and `AvailabilityClient` (`check_availability`).
  - `class LisskinsClient(*, api_key: str, base_url: str, timeout_seconds: float, client: httpx.AsyncClient | None = None)` with `buy(*, skin_id: int, partner: int, token: str, max_price_usd: Decimal, custom_id: str) -> Purchase`, `info(*, custom_ids: Sequence[str]) -> list[Purchase]`, `check_availability(ids: Sequence[int]) -> Availability`, `balance() -> Balance`.
  - `BUY_LINK_ERRORS`, `TRADE_LINK_ERRORS` (frozensets), `INFO_MAX_IDS = 200`, `client_for(settings, *, timeout_seconds: float | None = None) -> LisskinsClient`, `availability_client() -> AvailabilityClient` (a FastAPI dependency).
- Produces in `lisskins/export.py`: `@dataclass(frozen=True, slots=True) Sticker(name: str, image: str | None, slot: int | None, wear: float | None)`, `@dataclass(frozen=True, slots=True) Lot(id: int, name: str, price_units: int, paint_index: int | None, float_value: Decimal | None, paint_seed: int | None, asset_id: str | None, inspect_url: str | None, stickers: tuple[Sticker, ...])`, `to_units(price_usd: Decimal) -> int`, `lot_of(raw: Mapping[str, Any]) -> Lot | None`, `async read_export(url: str, on_lot: Callable[[Lot], None], *, timeout_seconds: float, client: httpx.AsyncClient | None = None) -> int` (the export's `last_update`, unix seconds), `ExportReader` (its Protocol).

- [ ] **Step 1: Write the failing tests**

```python
# apps/api/tests/unit/test_json_stream.py
"""``core.json_stream.ItemsScanner`` with a caller's own envelope (LIS-SKINS' export)."""

from __future__ import annotations

import json
import re

import pytest
from csmarket.core.json_stream import ItemsScanner

STATUS = re.compile(r'"status"\s*:\s*"success"')
LAST = re.compile(r'"last_update"\s*:\s*([0-9]+)')
BODY = json.dumps(
    {
        "status": "success",
        "last_update": 1759831200,
        "items": [{"id": 1, "name": "a ] {"}, {"id": 2, "stickers": [{"name": "x"}]}],
    }
)


@pytest.mark.parametrize("chunk", [1, 5, 64, 100_000])
def test_a_status_envelope_reads_with_its_own_patterns(chunk: int) -> None:
    scanner = ItemsScanner(success=STATUS, cursor=LAST)
    found: list[object] = []
    for start in range(0, len(BODY), chunk):
        found += scanner.feed(BODY[start : start + chunk])
    assert [o["id"] for o in found if isinstance(o, dict)] == [1, 2]
    assert scanner.finish() == "1759831200"


def test_the_default_patterns_refuse_a_status_envelope() -> None:
    scanner = ItemsScanner()
    scanner.feed(BODY)
    with pytest.raises(ValueError, match="not a success"):
        scanner.finish()


def test_a_failed_status_is_not_a_success() -> None:
    scanner = ItemsScanner(success=STATUS, cursor=LAST)
    scanner.feed(BODY.replace('"success"', '"error"'))
    with pytest.raises(ValueError, match="not a success"):
        scanner.finish()


def test_a_body_cut_inside_the_array_is_truncated() -> None:
    scanner = ItemsScanner(success=STATUS, cursor=LAST)
    scanner.feed(BODY[: BODY.index('{"id": 2')])
    with pytest.raises(ValueError, match="truncated"):
        scanner.finish()
```

```python
# apps/api/tests/contract/test_lisskins_client.py
"""LIS-SKINS API (respx): balance, buy, info, check-availability, every refusal code.

Shapes from the OpenAPI export of https://lis-skins.stoplight.io (2026-10-07). Every
partner, token, Steam id and skin id is made up.
"""

from __future__ import annotations

import json
from decimal import Decimal

import httpx
import pytest
import respx
from csmarket.modules.lisskins.api import (
    LisskinsClient,
    LisskinsError,
    LisskinsForbiddenError,
    LisskinsRateLimitedError,
    LisskinsUnavailableError,
    Purchase,
)

BASE = "https://api.lis-skins.com/v1"
SKIN = {
    "id": 125345,
    "name": "M4A4 | Spider Lily (Field-Tested)",
    "price": 2.03,
    "status": "processing",
    "return_reason": None,
    "return_charged_commission": None,
    "error": None,
    "steam_trade_offer_id": None,
    "steam_trade_offer_created_at": None,
    "steam_trade_offer_expiry_at": None,
    "steam_trade_offer_finished_at": None,
}
PURCHASE = {
    "purchase_id": 55,
    "steam_id": "76561190000000001",
    "created_at": "2026-10-07T14:50:08.000000Z",
    "custom_id": "order-1",
    "skins": [SKIN],
}


def _client() -> LisskinsClient:
    return LisskinsClient(api_key="k", base_url=BASE, timeout_seconds=1)


async def _buy(max_price: str = "2.03") -> Purchase:
    return await _client().buy(
        skin_id=125345,
        partner=39734273,
        token="AbCdEf12",
        max_price_usd=Decimal(max_price),
        custom_id="order-1",
    )


@respx.mock
async def test_balance_sends_the_bearer_key_and_parses() -> None:
    route = respx.get(f"{BASE}/user/balance").mock(
        return_value=httpx.Response(
            200,
            json={"data": {"balance": 99.96, "balance_locked": 1.5, "trade_protection_balance": 0}},
        )
    )
    b = await _client().balance()
    assert route.calls.last.request.headers["Authorization"] == "Bearer k"
    assert (b.available, b.locked, b.protected) == (Decimal("99.96"), Decimal("1.5"), Decimal(0))


@respx.mock
@pytest.mark.parametrize(("cap", "sent"), [("2.03", 2.03), ("12.349", 12.34), ("12.345", 12.34)])
async def test_buy_posts_one_id_and_a_cap_never_above_ours(cap: str, sent: float) -> None:
    route = respx.post(f"{BASE}/market/buy").mock(
        return_value=httpx.Response(200, json={"data": PURCHASE})
    )
    await _buy(cap)
    body = json.loads(route.calls.last.request.read())
    assert body == {
        "ids": [125345],
        "partner": "39734273",
        "token": "AbCdEf12",
        "max_price": sent,
        "custom_id": "order-1",
    }


@respx.mock
async def test_buy_parses_the_purchase_and_never_keeps_the_steam_id() -> None:
    respx.post(f"{BASE}/market/buy").mock(return_value=httpx.Response(200, json={"data": PURCHASE}))
    p = await _buy()
    assert (p.purchase_id, p.custom_id) == (55, "order-1")
    skin = p.skin
    assert (skin.id, skin.status, skin.price_usd) == (125345, "processing", Decimal("2.03"))
    assert "76561190000000001" not in repr(p)


@respx.mock
@pytest.mark.parametrize(
    "code",
    [
        "custom_id_already_exists",
        "skins_price_higher_than_max_price",
        "insufficient_funds",
        "invalid_trade_url",
        "user_trade_ban",
        "user_cant_trade",
        "private_inventory",
        "too_many_failed_attempts_for_user",
    ],
)
async def test_every_buy_refusal_carries_its_code(code: str) -> None:
    respx.post(f"{BASE}/market/buy").mock(return_value=httpx.Response(400, json={"error": code}))
    with pytest.raises(LisskinsError) as exc:
        await _buy()
    assert (exc.value.status, exc.value.code) == (400, code)
    assert not isinstance(exc.value, LisskinsForbiddenError)


@respx.mock
async def test_skins_unavailable_names_the_ids() -> None:
    respx.post(f"{BASE}/market/buy").mock(
        return_value=httpx.Response(
            400, json={"error": "skins_unavailable", "unavailable_ids": [125345]}
        )
    )
    with pytest.raises(LisskinsError) as exc:
        await _buy()
    assert (exc.value.code, exc.value.unavailable_ids) == ("skins_unavailable", (125345,))


@respx.mock
async def test_a_validation_error_is_a_refusal_with_its_code() -> None:
    respx.post(f"{BASE}/market/buy").mock(
        return_value=httpx.Response(422, json={"error": "invalid_partner_value"})
    )
    with pytest.raises(LisskinsError) as exc:
        await _buy()
    assert (exc.value.status, exc.value.code) == (422, "invalid_partner_value")


@respx.mock
@pytest.mark.parametrize(
    ("status", "error"),
    [
        (401, LisskinsForbiddenError),
        (403, LisskinsForbiddenError),
        (408, LisskinsUnavailableError),
        (500, LisskinsUnavailableError),
        (502, LisskinsUnavailableError),
        (503, LisskinsUnavailableError),
        (504, LisskinsUnavailableError),
    ],
)
async def test_http_statuses_map_to_errors(status: int, error: type[Exception]) -> None:
    respx.get(f"{BASE}/user/balance").mock(return_value=httpx.Response(status, json={}))
    with pytest.raises(error):
        await _client().balance()


@respx.mock
async def test_429_carries_retry_after() -> None:
    respx.post(f"{BASE}/market/buy").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "7"}, json={})
    )
    with pytest.raises(LisskinsRateLimitedError) as exc:
        await _buy()
    assert exc.value.retry_after == 7.0


@respx.mock
@pytest.mark.parametrize(
    "answer",
    [
        httpx.Response(200, text="<html>"),
        httpx.Response(200, json={"data": {"purchase_id": 55, "skins": []}}),
        httpx.Response(200, json={"nothing": 1}),
    ],
)
async def test_an_unreadable_buy_answer_is_unavailable(answer: httpx.Response) -> None:
    respx.post(f"{BASE}/market/buy").mock(return_value=answer)
    with pytest.raises(LisskinsUnavailableError):
        await _buy()


@respx.mock
async def test_a_transport_failure_is_unavailable() -> None:
    respx.post(f"{BASE}/market/buy").mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(LisskinsUnavailableError):
        await _buy()


@respx.mock
async def test_info_asks_by_custom_ids_and_skips_an_unreadable_entry() -> None:
    returned = {**SKIN, "status": "return", "return_reason": "trade_timeout"}
    route = respx.get(f"{BASE}/market/info").mock(
        return_value=httpx.Response(
            200, json={"data": [{**PURCHASE, "skins": [returned]}, {"purchase_id": "x"}]}
        )
    )
    found = await _client().info(custom_ids=["order-1", "order-2"])
    assert route.calls.last.request.url.params.get_list("custom_ids[]") == ["order-1", "order-2"]
    assert [(p.custom_id, p.skin.status, p.skin.return_reason) for p in found] == [
        ("order-1", "return", "trade_timeout")
    ]


async def test_info_refuses_more_than_200_ids_and_asks_nothing_for_none() -> None:
    with pytest.raises(ValueError, match="200"):
        await _client().info(custom_ids=[str(n) for n in range(201)])
    assert await _client().info(custom_ids=[]) == []


@respx.mock
async def test_check_availability_reads_prices_and_gone_ids() -> None:
    route = respx.get(f"{BASE}/market/check-availability").mock(
        return_value=httpx.Response(
            200,
            json={"data": {"available_skins": {"125345": 2.03}, "unavailable_skin_ids": [7]}},
        )
    )
    a = await _client().check_availability([125345, 7])
    assert route.calls.last.request.url.params.get_list("ids[]") == ["125345", "7"]
    assert (a.available, a.unavailable) == ({125345: Decimal("2.03")}, frozenset({7}))


@respx.mock
async def test_an_empty_available_list_reads_as_none_available() -> None:
    """PHP encodes an empty map as ``[]``."""
    respx.get(f"{BASE}/market/check-availability").mock(
        return_value=httpx.Response(
            200, json={"data": {"available_skins": [], "unavailable_skin_ids": [7]}}
        )
    )
    a = await _client().check_availability([7])
    assert (a.available, a.unavailable) == ({}, frozenset({7}))


async def test_no_key_is_unavailable_without_a_call() -> None:
    with pytest.raises(LisskinsUnavailableError):
        await LisskinsClient(api_key="", base_url=BASE, timeout_seconds=1).balance()
```

```python
# apps/api/tests/contract/test_lisskins_export.py
"""The public export (respx): only instant, unlocked lots; ``last_update``; a cut, failed or
foreign body is an outage, never an empty market."""

from __future__ import annotations

import json
from decimal import Decimal

import httpx
import pytest
import respx
from csmarket.modules.lisskins.api import LisskinsUnavailableError, Lot, read_export

URL = "https://lis-skins.com/market_export_json/api_csgo_full.json"
LOT = {
    "id": 9001,
    "name": "AK-47 | Redline (Field-Tested)",
    "price": 12.35,
    "unlock_at": None,
    "item_class_id": "1",
    "created_at": "2026-10-07T10:00:00.000000Z",
    "item_float": "0.2512345678",
    "name_tag": None,
    "item_paint_index": 282,
    "item_paint_seed": 661,
    "item_asset_id": "38000000001",
    "item_link": "steam://rungame/730/76561202255233023/+csgo_econ_action_preview%20S1A2D3",
    "stickers": [
        {"name": "Sticker | Crown (Foil)", "image": "https://steamcdn-a.akamaihd.net/x.png", "wear": 0, "slot": 1},
        "junk",
    ],
    "delivery_type": 1,
}


def _body(items: list[object], status: str = "success") -> str:
    return json.dumps({"status": status, "last_update": 1759831200, "items": items})


async def _read(body: str | httpx.Response) -> tuple[int, list[Lot]]:
    respx.get(URL).mock(
        return_value=body if isinstance(body, httpx.Response) else httpx.Response(200, text=body)
    )
    got: list[Lot] = []
    last = await read_export(URL, got.append, timeout_seconds=1)
    return last, got


@respx.mock
async def test_only_instant_unlocked_priced_lots_are_kept() -> None:
    items = [
        LOT,
        {**LOT, "id": 9002, "delivery_type": 2},
        {**LOT, "id": 9003, "unlock_at": "2026-10-10T10:00:00.000000Z"},
        {**LOT, "id": 9004, "price": 0},
        {**LOT, "id": "nope"},
    ]
    last, got = await _read(_body(items))
    assert last == 1759831200
    assert [lot.id for lot in got] == [9001]
    lot = got[0]
    assert (lot.price_units, lot.paint_index, lot.paint_seed, lot.asset_id) == (
        12_350,
        282,
        661,
        "38000000001",
    )
    assert lot.float_value == Decimal("0.251235")
    assert lot.inspect_url is not None and lot.inspect_url.startswith("steam://")
    assert [(s.name, s.slot, s.wear) for s in lot.stickers] == [("Sticker | Crown (Foil)", 1, 0.0)]


@respx.mock
async def test_the_export_is_asked_with_a_browser_agent() -> None:
    route = respx.get(URL).mock(return_value=httpx.Response(200, text=_body([LOT])))
    await read_export(URL, lambda _lot: None, timeout_seconds=1)
    assert route.calls.last.request.headers["User-Agent"].startswith("Mozilla/5.0")


@respx.mock
@pytest.mark.parametrize(
    "answer",
    [
        httpx.Response(200, text=_body([LOT, LOT])[:-40]),  # cut inside the array
        httpx.Response(200, text=_body([LOT], status="error")),
        httpx.Response(200, text="<html>maintenance</html>"),
        httpx.Response(503, text="busy"),
    ],
)
async def test_a_cut_failed_or_foreign_body_is_unavailable(answer: httpx.Response) -> None:
    with pytest.raises(LisskinsUnavailableError):
        await _read(answer)


@respx.mock
async def test_a_transport_failure_is_unavailable() -> None:
    respx.get(URL).mock(side_effect=httpx.ConnectError("down"))
    with pytest.raises(LisskinsUnavailableError):
        await read_export(URL, lambda _lot: None, timeout_seconds=1)
```

- [ ] **Step 2: Run them**

Run: `cd apps/api && uv run pytest tests/unit/test_json_stream.py tests/contract/test_lisskins_client.py tests/contract/test_lisskins_export.py -q`
Expected: FAIL — `ModuleNotFoundError: csmarket.core.json_stream`, `ImportError` from `lisskins.api`.

- [ ] **Step 3: Generalise and move the scanner**

```bash
git mv apps/api/src/csmarket/modules/skinslink/stream.py apps/api/src/csmarket/core/json_stream.py
```

In `core/json_stream.py`: the module docstring says it reads any `{…, "items": [ … ], …}` body without holding it whole (Skinslink's sale list, LIS-SKINS' export). Rename the patterns and take them as arguments:

```python
#: Skinslink's envelope: ``{"success": true, "data": {…, "last_update_at": "…"}}``.
SUCCESS_TRUE = re.compile(r'"success"\s*:\s*true')
LAST_UPDATE_AT = re.compile(r'"last_update_at"\s*:\s*"([^"]*)"')


class ItemsScanner:
    """Incremental reader of one JSON object whose ``"items": [ … ]`` array is huge.

    Args:
        success: Must match the text around the array once the body ended
            (Skinslink: :data:`SUCCESS_TRUE`; LIS-SKINS: ``"status": "success"``).
        cursor: Its group 1 is what :meth:`finish` returns
            (Skinslink: :data:`LAST_UPDATE_AT`; LIS-SKINS: ``last_update``).
    """

    def __init__(
        self, *, success: re.Pattern[str] = SUCCESS_TRUE, cursor: re.Pattern[str] = LAST_UPDATE_AT
    ) -> None:
        self._buf = ""
        self._head = ""
        self._tail = ""
        self._state = "head"
        self._success = success
        self._cursor = cursor
```

and in `finish()` use `self._success` / `self._cursor` instead of `_SUCCESS` / `_CURSOR` (the rest of the class is unchanged; `__all__ = ["LAST_UPDATE_AT", "SUCCESS_TRUE", "ItemsScanner"]`). In `skinslink/client.py` and `tests/contract/test_skinslink_client.py` replace `from csmarket.modules.skinslink.stream import ItemsScanner` with `from csmarket.core.json_stream import ItemsScanner`.

- [ ] **Step 4: Add the metric**

`core/metrics.py`, beside the Skinslink counter:

```python
#: A LIS-SKINS API call (spec 2026-10-07); ``export`` is the public price export.
LisskinsEndpoint = Literal["export", "buy", "info", "check", "balance"]
#: ``refused`` = a 4xx with an ``error`` code; ``unavailable`` = transport, 408/5xx, an
#: unreadable or cut body.
LisskinsOutcome = Literal["ok", "refused", "forbidden", "rate_limited", "unavailable"]

_LISSKINS_ENDPOINTS = frozenset(("export", "buy", "info", "check", "balance"))
_LISSKINS_OUTCOMES = frozenset(("ok", "refused", "forbidden", "rate_limited", "unavailable"))

LISSKINS_CALLS = Counter(
    "csmarket_lisskins_calls_total",
    "LIS-SKINS API calls by endpoint and outcome (alert: LisskinsBuyFailures).",
    ("endpoint", "outcome"),
)
```

and beside `record_skinslink_call`:

```python
def record_lisskins_call(endpoint: LisskinsEndpoint, outcome: LisskinsOutcome) -> None:
    """Count one LIS-SKINS call by how it ended.

    A value outside the closed sets becomes ``"other"``. Never raises.
    """
    _inc(
        LISSKINS_CALLS,
        "csmarket_lisskins_calls_total",
        {
            "endpoint": endpoint if endpoint in _LISSKINS_ENDPOINTS else "other",
            "outcome": outcome if outcome in _LISSKINS_OUTCOMES else "other",
        },
    )
```

Add `"LisskinsEndpoint"`, `"LisskinsOutcome"`, `"record_lisskins_call"` to `__all__`.

- [ ] **Step 5: Write `lisskins/values.py`**

```python
"""Reading LIS-SKINS' JSON values field by field (the client and the export share it)."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation


def decimal_of(value: object) -> Decimal | None:
    """A JSON number (or numeric string) as ``Decimal`` via its text; ``None`` otherwise."""
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def int_of(value: object) -> int | None:
    """An integer, or a string of digits, as ``int``; ``None`` otherwise."""
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def str_of(value: object) -> str | None:
    """A non-empty string, or ``None``."""
    return value if isinstance(value, str) and value else None


__all__ = ["decimal_of", "int_of", "str_of"]
```

- [ ] **Step 6: Write `lisskins/client.py`**

```python
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
    """401 / 403: the key is wrong or revoked, or this host may not use it."""


class LisskinsUnavailableError(Exception):
    """No answer worth reading: transport, 408/5xx, an unreadable body, or no key."""


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
        if not self._api_key:
            raise LisskinsUnavailableError("no api key")
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
]
```

- [ ] **Step 7: Write `lisskins/export.py`**

```python
"""LIS-SKINS' public price export, read as a stream (spec 2026-10-07 §3).

``GET <lisskins_export_url>`` (no key) is one JSON object —
``{"status": "success", "last_update": <unix>, "items": [ … ]}``, ~855 MB, ~2.4 M lots — so
it is never in memory whole: each element of ``items`` becomes a :class:`Lot` as soon as it
is complete and goes to ``on_lot``, if it is one we sell (``delivery_type`` 1, not
trade-locked, a usable id, name and price).
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Protocol

import httpx

from csmarket.core.json_stream import ItemsScanner
from csmarket.core.metrics import record_lisskins_call
from csmarket.modules.lisskins.client import LisskinsUnavailableError
from csmarket.modules.lisskins.values import decimal_of, int_of, str_of

STATUS_SUCCESS = re.compile(r'"status"\s*:\s*"success"')
LAST_UPDATE = re.compile(r'"last_update"\s*:\s*([0-9]+)')
#: ``delivery_type`` of a lot LIS-SKINS' own bot sends at once (2 = the seller, ≤ 12 h).
INSTANT = 1
#: The export's CDN answered the 2026-10-07 probe only with a browser-like agent.
USER_AGENT = "Mozilla/5.0 (compatible; csmarket.uz)"
_UNIT = Decimal(1)
_FLOAT_PLACES = Decimal("0.000001")


@dataclass(frozen=True, slots=True)
class Sticker:
    """A sticker on a lot, as LIS-SKINS names it."""

    name: str
    image: str | None
    slot: int | None
    wear: float | None


@dataclass(frozen=True, slots=True)
class Lot:
    """One instant, unlocked lot of the export, in units (1000 = $1)."""

    id: int
    name: str
    price_units: int
    paint_index: int | None
    float_value: Decimal | None
    paint_seed: int | None
    #: The Steam asset — the same asset on Skinslink is shown once (``skins.merge_offers``).
    asset_id: str | None
    inspect_url: str | None
    stickers: tuple[Sticker, ...]


class ExportReader(Protocol):
    """:func:`read_export`'s shape (the snapshot tests pass a scripted one)."""

    async def __call__(
        self, url: str, on_lot: Callable[[Lot], None], *, timeout_seconds: float
    ) -> int:
        """Feed every sellable lot to ``on_lot``; return ``last_update``."""
        ...


def to_units(price_usd: Decimal) -> int:
    """USD as units (1000 = $1), half up."""
    return int((price_usd * 1000).quantize(_UNIT, rounding=ROUND_HALF_UP))


def _float(value: object) -> Decimal | None:
    number = decimal_of(value)
    if number is None or not Decimal(0) <= number <= Decimal(1):
        return None
    return number.quantize(_FLOAT_PLACES)


def _stickers(value: object) -> tuple[Sticker, ...]:
    found: list[Sticker] = []
    for raw in value if isinstance(value, list) else []:
        name = str_of(raw.get("name")) if isinstance(raw, Mapping) else None
        if name is None or not isinstance(raw, Mapping):
            continue
        wear = decimal_of(raw.get("wear"))
        found.append(
            Sticker(
                name=name,
                image=str_of(raw.get("image")),
                slot=int_of(raw.get("slot")),
                wear=None if wear is None else float(wear),
            )
        )
    return tuple(found)


# Any: one lot object of the export, read field by field.
def lot_of(raw: Mapping[str, Any]) -> Lot | None:
    """A lot we may sell, or ``None``: slow delivery, trade-locked, or unusable."""
    if raw.get("delivery_type") != INSTANT or raw.get("unlock_at") is not None:
        return None
    lot_id, name, price = int_of(raw.get("id")), str_of(raw.get("name")), decimal_of(raw.get("price"))
    if lot_id is None or name is None or price is None or price <= 0:
        return None
    link = raw.get("item_link")
    return Lot(
        id=lot_id,
        name=name,
        price_units=to_units(price),
        paint_index=int_of(raw.get("item_paint_index")),
        float_value=_float(raw.get("item_float")),
        paint_seed=int_of(raw.get("item_paint_seed")),
        asset_id=str_of(raw.get("item_asset_id")),
        inspect_url=link if isinstance(link, str) and link.startswith("steam://") else None,
        stickers=_stickers(raw.get("stickers")),
    )


@asynccontextmanager
async def _session(
    client: httpx.AsyncClient | None, timeout_seconds: float
) -> AsyncIterator[httpx.AsyncClient]:
    if client is not None:
        yield client
        return
    async with httpx.AsyncClient(timeout=timeout_seconds) as fresh:
        yield fresh


def _unavailable(reason: str) -> LisskinsUnavailableError:
    record_lisskins_call("export", "unavailable")
    return LisskinsUnavailableError(reason)


async def read_export(
    url: str,
    on_lot: Callable[[Lot], None],
    *,
    timeout_seconds: float,
    client: httpx.AsyncClient | None = None,
) -> int:
    """Stream the export; ``on_lot`` gets every sellable lot, in order.

    Returns:
        The export's ``last_update`` (unix seconds).

    Raises:
        LisskinsUnavailableError: Transport, a non-200, a body that is not the export, one
            cut short, or one that does not say ``"status": "success"`` — never read as an
            empty market.
    """
    scanner = ItemsScanner(success=STATUS_SUCCESS, cursor=LAST_UPDATE)
    try:
        async with (
            _session(client, timeout_seconds) as http,
            http.stream("GET", url, headers={"User-Agent": USER_AGENT}) as resp,
        ):
            if resp.status_code != 200:
                raise _unavailable(f"http {resp.status_code}")
            async for text in resp.aiter_text():
                for raw in scanner.feed(text):
                    if isinstance(raw, Mapping) and (lot := lot_of(raw)) is not None:
                        on_lot(lot)
        last = scanner.finish()
    except httpx.HTTPError as exc:
        raise _unavailable(type(exc).__name__) from exc
    except ValueError as exc:  # not the export, cut short, or not a success
        raise _unavailable("unexpected body") from exc
    if last is None:
        raise _unavailable("no last_update")
    record_lisskins_call("export", "ok")
    return int(last)


__all__ = ["INSTANT", "ExportReader", "Lot", "Sticker", "lot_of", "read_export", "to_units"]
```

`lisskins/api.py` re-exports every name of `client.__all__` and `export.__all__` (`from … import (…)` blocks and a sorted `__all__`, as `skinslink/api.py` does).

- [ ] **Step 8: Run the tests and the gates**

Run: `cd apps/api && uv run pytest tests/unit/test_json_stream.py tests/contract/test_lisskins_client.py tests/contract/test_lisskins_export.py tests/contract/test_skinslink_client.py -q && cd ../.. && make lint typecheck`
Expected: PASS (the Skinslink contract suite unchanged); clean.

- [ ] **Step 9: Commit**

```bash
git add apps/api/src/csmarket/core apps/api/src/csmarket/modules/skinslink apps/api/src/csmarket/modules/lisskins apps/api/tests/unit/test_json_stream.py apps/api/tests/contract
git commit -m "feat(api/lisskins): the LIS-SKINS client and the streamed export reader; the items scanner moves to core" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Tables and the migration (0022)

**Files:**

- Create: `apps/api/src/csmarket/modules/lisskins/models.py`, `apps/api/migrations/versions/0022_lisskins.py`
- Modify: `apps/api/src/csmarket/modules/skins/models.py:81-85` (two columns after `skinslink_count`, one property)
- Modify: `apps/api/src/csmarket/modules/orders/models.py:50` (`ORDER_SOURCES`; the `offer_id` / `listing_id` comments name `ls:`)
- Modify: `apps/api/migrations/env.py`, `apps/scheduler/src/csmarket_scheduler/main.py`, `apps/worker/src/csmarket_worker/consumer.py` (import `csmarket.modules.lisskins.models` beside Skinslink's, so mappers resolve)
- Modify: `apps/api/tests/integration/conftest.py` (`_EMPTY_IN_ORDER`)
- Modify: `apps/api/src/csmarket/modules/lisskins/api.py` (export the models)
- Test: `apps/api/tests/integration/test_lisskins_models.py`

**Interfaces:**

- Produces: `LisskinsOffer` (`lisskins_offers`: `id: int` PK = LIS-SKINS skin id, `skin_item_id: str` FK `skin_items` CASCADE, `price_units: int`, `float_value: Decimal | None`, `paint_seed: int | None`, `asset_id: str | None`, `inspect_url: str | None`, `stickers: list[dict]` JSONB `{name, image, slot, wear}`, `updated_at`); `LisskinsState` (`lisskins_state`, row 1: `snapshot_at` (the export's `last_update`), `synced_at`, `lots: int` — the previous applied tick's sellable lots, for the collapse rule); `LisskinsPurchase` (`lisskins_purchases`: `order_id` PK, `custom_id` unique, `skin_id: int`, `paid_units: int`, `purchase_id: int | None`, `status`, `return_reason`, `error`, `steam_trade_offer_id`, `offer_expiry_at`, `amount_units`, `buy_pending`, `buy_unconfirmed_at`, `attention_reason`, `last_polled_at`, `resolved_at`, `resolved_by`, `resolved_note`, `created_at`, `updated_at`).
- Produces: `SkinItem.lisskins_min_units: int | None`, `SkinItem.lisskins_count: int` (default 0), and `SkinItem.stock_count -> int` (`count_auto + skinslink_count + lisskins_count`, a plain property).
- Produces: `ORDER_SOURCES = ("waxpeer", "skinslink", "lisskins")`.
- Decision: `lisskins_state.lots` is not in the spec's column list; the "< 50 % of the previous tick" rule (spec §3) needs the previous count stored.

- [ ] **Step 1: Write the failing test**

```python
# apps/api/tests/integration/test_lisskins_models.py
"""LIS-SKINS tables: offers go with their item, one purchase per custom id, a third source."""

from __future__ import annotations

import pytest
from csmarket.modules.lisskins.models import LisskinsOffer, LisskinsPurchase, LisskinsState
from csmarket.modules.skins.models import SkinItem
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.orders_factory import make_item_and_rate, make_order


async def _ls_order(db: AsyncSession) -> str:
    order = await make_order(
        db, status="buying", source="lisskins", offer_id="ls:125345", listing_id=None
    )
    return order.id


async def test_a_lisskins_order_keeps_its_purchase(db_session: AsyncSession) -> None:
    order_id = await _ls_order(db_session)
    db_session.add(
        LisskinsPurchase(
            order_id=order_id, custom_id=order_id, skin_id=125345, paid_units=12_340, buy_pending=True
        )
    )
    await db_session.commit()
    row = await db_session.get(LisskinsPurchase, order_id)
    assert row is not None
    assert (row.skin_id, row.buy_pending, row.status, row.attention_reason) == (
        125345,
        True,
        None,
        None,
    )


async def test_one_purchase_per_custom_id(db_session: AsyncSession) -> None:
    a, b = await _ls_order(db_session), await _ls_order(db_session)
    db_session.add_all(
        [
            LisskinsPurchase(order_id=a, custom_id="same", skin_id=1, paid_units=1),
            LisskinsPurchase(order_id=b, custom_id="same", skin_id=2, paid_units=1),
        ]
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()


async def test_an_unknown_attention_reason_is_refused(db_session: AsyncSession) -> None:
    order_id = await _ls_order(db_session)
    db_session.add(
        LisskinsPurchase(
            order_id=order_id, custom_id=order_id, skin_id=1, paid_units=1, attention_reason="nope"
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()


async def test_an_unknown_source_is_refused(db_session: AsyncSession) -> None:
    with pytest.raises(IntegrityError):
        await make_order(db_session, source="ebay")


async def test_offers_go_with_their_item(db_session: AsyncSession) -> None:
    item, _ = await make_item_and_rate(db_session)
    assert (item.lisskins_min_units, item.lisskins_count, item.stock_count) == (None, 0, 0)
    db_session.add_all(
        [LisskinsOffer(id=1, skin_item_id=item.id, price_units=1000), LisskinsState(id=1, lots=1)]
    )
    await db_session.commit()
    await db_session.execute(delete(SkinItem).where(SkinItem.id == item.id))
    await db_session.commit()
    assert await db_session.scalar(select(LisskinsOffer.id)) is None
```

- [ ] **Step 2: Run it**

Run: `cd apps/api && uv run pytest tests/integration/test_lisskins_models.py -q`
Expected: FAIL — `ModuleNotFoundError: csmarket.modules.lisskins.models`.

- [ ] **Step 3: Write the models**

`modules/lisskins/models.py`:

```python
"""SQLAlchemy ORM for the ``lisskins`` module (spec 2026-10-07).

- :class:`LisskinsOffer` — the 10 cheapest instant lots of each catalogue item, from the
  public export (``lisskins.snapshot``); ``id`` is LIS-SKINS' skin id, what ``market/buy``
  takes.
- :class:`LisskinsState` — row 1: when the export was made, when we applied it, how many
  sellable lots it had.
- :class:`LisskinsPurchase` — the purchase behind one LIS-SKINS order.

Units are 1000 = $1, as every source's.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from csmarket.core.db import Base
from csmarket.modules.orders.models import ATTENTION_REASONS


def _in(values: tuple[str, ...]) -> str:
    """``('a', 'b')`` as a SQL ``IN`` list."""
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


def _ts() -> Mapped[datetime]:
    return mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


def _at() -> Mapped[datetime | None]:
    return mapped_column(DateTime(timezone=True), nullable=True)


class LisskinsOffer(Base):
    """One of the 10 cheapest instant lots of a catalogue item."""

    __tablename__ = "lisskins_offers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    skin_item_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("skin_items.id", ondelete="CASCADE"), nullable=False
    )
    price_units: Mapped[int] = mapped_column(BigInteger, nullable=False)
    float_value: Mapped[Decimal | None] = mapped_column(Numeric(7, 6), nullable=True)
    paint_seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: The Steam asset id (``item_asset_id``).
    asset_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    inspect_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Any: ``[{"name": str, "image": str | None, "slot": int | None, "wear": float | None}]``
    # as LIS-SKINS names them (``export.Sticker``).
    stickers: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb"), default=list
    )
    updated_at: Mapped[datetime] = _ts()

    __table_args__ = (Index("ix_lisskins_offers_item_price", "skin_item_id", "price_units"),)


class LisskinsState(Base):
    """Row 1: the snapshot's freshness and size."""

    __tablename__ = "lisskins_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: The export's own ``last_update`` — what freshness is judged by.
    snapshot_at: Mapped[datetime | None] = _at()
    synced_at: Mapped[datetime | None] = _at()
    #: Sellable lots in the last applied export (a tick with under half of it is refused).
    lots: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), default=0)

    __table_args__ = (CheckConstraint("id = 1", name="singleton"),)


class LisskinsPurchase(Base):
    """The LIS-SKINS purchase behind one order."""

    __tablename__ = "lisskins_purchases"

    order_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("orders.id", ondelete="CASCADE"), primary_key=True
    )
    #: Our idempotency key at LIS-SKINS: the order id, ``<order id>:2`` for a substitute.
    custom_id: Mapped[str] = mapped_column(String(64), nullable=False)
    #: The LIS-SKINS lot being bought.
    skin_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    #: The cap we agreed to pay, units.
    paid_units: Mapped[int] = mapped_column(Integer, nullable=False)
    purchase_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    #: The skin's status word (``processing`` … ``return``); ``NULL`` before any answer.
    status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    return_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error: Mapped[str | None] = mapped_column(String(32), nullable=True)
    steam_trade_offer_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    offer_expiry_at: Mapped[datetime | None] = _at()
    #: What LIS-SKINS charged, units.
    amount_units: Mapped[int | None] = mapped_column(Integer, nullable=True)
    buy_pending: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"), default=False
    )
    #: When a buy's answer was lost; resolved by ``market/info`` (``lisskins_reconcile``).
    buy_unconfirmed_at: Mapped[datetime | None] = _at()
    attention_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_polled_at: Mapped[datetime | None] = _at()
    resolved_at: Mapped[datetime | None] = _at()
    resolved_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resolved_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _ts()

    __table_args__ = (
        UniqueConstraint("custom_id", name="uq_lisskins_purchases_custom_id"),
        CheckConstraint(f"attention_reason IN {_in(ATTENTION_REASONS)}", name="attention_reason"),
    )


__all__ = ["LisskinsOffer", "LisskinsPurchase", "LisskinsState"]
```

`skins/models.py`, after `skinslink_count`:

```python
    # ---- the LIS-SKINS side (same units), written by the snapshot (``lisskins.snapshot``) ----
    lisskins_min_units: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    lisskins_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"), default=0
    )
```

and at the end of the class body:

```python
    @property
    def stock_count(self) -> int:
        """Every source's lots: the liquidity the pricing rules and the card count read."""
        return self.count_auto + self.skinslink_count + self.lisskins_count
```

`orders/models.py`: `ORDER_SOURCES = ("waxpeer", "skinslink", "lisskins")` with the comment `#: Where an order's skin is bought (specs 2026-10-06, 2026-10-07).`

`tests/integration/conftest.py`, in `_EMPTY_IN_ORDER` right after `"skinslink_state",`: `"lisskins_purchases", "lisskins_offers", "lisskins_state",`.

- [ ] **Step 4: Write the migration**

```python
# apps/api/migrations/versions/0022_lisskins.py
"""lisskins: offers, state and purchases; skin_items and orders learn a third source

LIS-SKINS becomes a buy source beside Skinslink (spec 2026-10-07, ADR-0012): the 10
cheapest instant lots per catalogue item from its public export, the snapshot's freshness,
and the purchase behind each LIS-SKINS order.

Revision ID: 0022_lisskins
Revises: 0021_inspect_stickers
Create Date: 2026-10-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0022_lisskins"
down_revision: str | None = "0021_inspect_stickers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ATTENTION = (
    "'buy_unconfirmed', 'ambiguous_trade', 'rolled_back', 'source_forbidden', 'audit_divergence'"
)


def _ts(name: str) -> sa.Column[object]:
    return sa.Column(
        name, sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
    )


def _at(name: str) -> sa.Column[object]:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=True)


def _tables() -> None:
    op.create_table(
        "lisskins_offers",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column(
            "skin_item_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("skin_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("price_units", sa.BigInteger(), nullable=False),
        sa.Column("float_value", sa.Numeric(7, 6), nullable=True),
        sa.Column("paint_seed", sa.Integer(), nullable=True),
        sa.Column("asset_id", sa.String(32), nullable=True),
        sa.Column("inspect_url", sa.Text(), nullable=True),
        sa.Column(
            "stickers", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        _ts("updated_at"),
    )
    op.create_index(
        "ix_lisskins_offers_item_price", "lisskins_offers", ["skin_item_id", "price_units"]
    )
    op.create_table(
        "lisskins_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        _at("snapshot_at"),
        _at("synced_at"),
        sa.Column("lots", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.CheckConstraint("id = 1", name="singleton"),
    )
    op.create_table(
        "lisskins_purchases",
        sa.Column(
            "order_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("orders.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("custom_id", sa.String(64), nullable=False),
        sa.Column("skin_id", sa.BigInteger(), nullable=False),
        sa.Column("paid_units", sa.Integer(), nullable=False),
        sa.Column("purchase_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(16), nullable=True),
        sa.Column("return_reason", sa.String(32), nullable=True),
        sa.Column("error", sa.String(32), nullable=True),
        sa.Column("steam_trade_offer_id", sa.String(32), nullable=True),
        _at("offer_expiry_at"),
        sa.Column("amount_units", sa.Integer(), nullable=True),
        sa.Column("buy_pending", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        _at("buy_unconfirmed_at"),
        sa.Column("attention_reason", sa.String(32), nullable=True),
        _at("last_polled_at"),
        _at("resolved_at"),
        sa.Column("resolved_by", sa.String(64), nullable=True),
        sa.Column("resolved_note", sa.Text(), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.UniqueConstraint("custom_id", name="uq_lisskins_purchases_custom_id"),
        sa.CheckConstraint(f"attention_reason IN ({_ATTENTION})", name="attention_reason"),
    )


def upgrade() -> None:
    """Create the LIS-SKINS tables; add the roll-up columns; allow the third source."""
    _tables()
    op.add_column("skin_items", sa.Column("lisskins_min_units", sa.BigInteger(), nullable=True))
    op.add_column(
        "skin_items",
        sa.Column("lisskins_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.drop_constraint("source", "orders", type_="check")
    op.create_check_constraint(
        "source", "orders", "source IN ('waxpeer', 'skinslink', 'lisskins')"
    )


def downgrade() -> None:
    """Back to two sources (LIS-SKINS orders must be gone: the check refuses them)."""
    op.drop_constraint("source", "orders", type_="check")
    op.create_check_constraint("source", "orders", "source IN ('waxpeer', 'skinslink')")
    op.drop_column("skin_items", "lisskins_count")
    op.drop_column("skin_items", "lisskins_min_units")
    op.drop_table("lisskins_purchases")
    op.drop_table("lisskins_state")
    op.drop_index("ix_lisskins_offers_item_price", table_name="lisskins_offers")
    op.drop_table("lisskins_offers")
```

Import the models in `migrations/env.py`, scheduler `main.py` and worker `consumer.py` (`from csmarket.modules.lisskins import models as _lisskins_models  # noqa: F401`, beside the Skinslink line).

- [ ] **Step 5: Run the test, the migration round trip and the gates**

Run: `cd apps/api && uv run pytest tests/integration/test_lisskins_models.py tests/integration/test_orders_models.py tests/integration/test_skinslink_models.py -q && cd ../.. && make lint typecheck`
Expected: PASS (the integration conftest migrates a fresh container to head, so 0022 runs); clean. Then, with the dev stack up: `make migrate` and `docker compose exec api alembic downgrade 0021_inspect_stickers && docker compose exec api alembic upgrade head` — both succeed.

- [ ] **Step 6: Commit**

```bash
git add apps/api/src/csmarket/modules/lisskins apps/api/src/csmarket/modules/skins/models.py apps/api/src/csmarket/modules/orders/models.py apps/api/migrations apps/scheduler/src apps/worker/src apps/api/tests/integration/conftest.py apps/api/tests/integration/test_lisskins_models.py
git commit -m "feat(api/lisskins): offers, state and purchases tables; skin_items and orders learn a third source" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: The snapshot, its roll-up, the cost from every source, and the jobs

Decisions: (a) a lot whose name carries no Doppler phase is placed by `item_paint_index` against `skin_items.paint_index` among the phased rows of that name (each phase is its own paint), else on the phaseless row — LIS-SKINS names Dopplers without the phase; (b) freshness is judged by the export's own `last_update` (`lisskins_state.snapshot_at`), so an export LIS-SKINS stopped refreshing reads stale even while our download succeeds; (c) the snapshot writes `lisskins_min_units` / `lisskins_count` itself (the count covers every lot, not only the 10 kept) and `lisskins.rollup` keeps them honest (cleared when off/stale, `active` restored after a Waxpeer tick); (d) the apply runs in `skins.source_prices` under the pricing lock and reprices in the same transaction, as `sync_prices` does for Waxpeer; (e) `skinslink.prices` becomes `sources.prices` (`sync_source_prices`, job file `source_prices.py`).

**Files:**

- Create: `apps/api/src/csmarket/modules/lisskins/snapshot.py`, `apps/api/src/csmarket/modules/lisskins/rollup.py`
- Create: `apps/api/src/csmarket/modules/skins/source_prices.py` (takes `sync_skinslink_prices` → `sync_source_prices` and `_clear_waxpeer_stock` out of `prices.py`; adds `sync_lisskins`)
- Modify: `apps/api/src/csmarket/modules/skins/prices.py` (the two functions leave; `sync_prices` rolls LIS-SKINS up; `apply_prices`' deactivation keeps LIS-SKINS stock on sale)
- Modify: `apps/api/src/csmarket/modules/skins/repricing.py` (`cost_units(*units)`; `reprice_rows` reads the LIS-SKINS columns)
- Modify: `apps/api/src/csmarket/modules/skinslink/rollup.py:33-35` (`_clear` keeps LIS-SKINS stock on sale)
- Modify: `apps/api/src/csmarket/core/metrics.py` (gauge `csmarket_lisskins_snapshot_timestamp_seconds`, `set_lisskins_snapshot(at_unix: float)`)
- Create: `apps/scheduler/src/csmarket_scheduler/jobs/lisskins_snapshot.py`
- Move: `apps/scheduler/src/csmarket_scheduler/jobs/skinslink_prices.py` → `source_prices.py`; `apps/scheduler/tests/test_skinslink_prices.py` → `test_source_prices.py`
- Modify: `apps/scheduler/src/csmarket_scheduler/main.py`, `apps/scheduler/tests/test_main.py`, `apps/api/tests/integration/test_skinslink_rollup.py`, `apps/api/tests/integration/test_waxpeer_buy_off.py` (the rename)
- Test: `apps/api/tests/integration/test_lisskins_snapshot.py`, `apps/api/tests/integration/test_lisskins_rollup.py`, `apps/api/tests/unit/test_skins_reprice_cost.py`, `apps/scheduler/tests/test_lisskins_snapshot.py`

**Interfaces:**

- Consumes: `Lot`, `ExportReader`, `read_export`, `LisskinsUnavailableError` (Task 2); `LisskinsOffer`, `LisskinsState`, `SkinItem.lisskins_*` (Task 3).
- Produces in `lisskins/snapshot.py`: `KEEP = 10`, `MIN_SHARE = 0.5`; `class CatalogueIndex(rows: Iterable[tuple[str, str, str, int | None]])` with `item_for(name: str, paint_index: int | None) -> str | None`; `async load_index(db) -> CatalogueIndex`; `class Collector(index, *, keep=KEEP)` with `add(lot: Lot) -> None`, `lots: int`, `unmapped: int`, `items: dict[str, _Kept]`, `cheapest(item_id) -> list[Lot]`, `summary() -> dict[str, tuple[int, int]]` (`(min units, count)` per item); `@dataclass(frozen=True) SnapshotResult(refused: bool, lots: int, unmapped: int = 0, items: int = 0, written: int = 0, removed: int = 0, snapshot_at: datetime | None = None)`; `async apply_snapshot(db, collected, *, snapshot_at: datetime, now: datetime) -> SnapshotResult` (never commits); `async snapshot_fresh(db, *, settings, now) -> bool`.
- Produces in `lisskins/rollup.py`: `async rollup(db, *, settings, now) -> int` (never commits).
- Produces in `skins/source_prices.py`: `async sync_lisskins(session_factory, redis, *, settings, reader: ExportReader = read_export, now: Callable[[], datetime] = clock.now) -> SnapshotResult`; `async sync_source_prices(session_factory, redis, *, settings, at: datetime) -> bool`.
- Produces in `skins/repricing.py`: `cost_units(*units: int | None) -> int | None`.
- Produces in `core/metrics.py`: `set_lisskins_snapshot(at_unix: float) -> None`.

- [ ] **Step 1: Write the failing tests**

```python
# apps/api/tests/integration/test_lisskins_snapshot.py
"""The LIS-SKINS snapshot: mapping (Dopplers by paint), the ten cheapest, changes and
deletes, the collapse rule, a cut export, and prices from the cheaper source."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from csmarket.core.config import get_settings
from csmarket.core.ids import new_id
from csmarket.core.redis import get_redis
from csmarket.modules.lisskins.api import (
    ExportReader,
    LisskinsUnavailableError,
    Lot,
    SnapshotResult,
    Sticker,
)
from csmarket.modules.lisskins.models import LisskinsOffer, LisskinsState
from csmarket.modules.skins.models import SkinItem
from csmarket.modules.skins.pricing import quote
from csmarket.modules.skins.settings import load_rules
from csmarket.modules.skins.source_prices import sync_lisskins
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.integration.orders_factory import make_item_and_rate

LAST = 1_759_831_200
NOW = datetime.fromtimestamp(LAST, UTC) + timedelta(minutes=1)
SETTINGS = get_settings().model_copy(update={"lisskins_enabled": True, "lisskins_api_key": "k"})


def _lot(id_: int, name: str, units: int, *, paint: int | None = None) -> Lot:
    return Lot(
        id=id_,
        name=name,
        price_units=units,
        paint_index=paint,
        float_value=Decimal("0.25"),
        paint_seed=1,
        asset_id=str(38_000_000_000 + id_),
        inspect_url=None,
        stickers=(Sticker(name="Sticker | Crown (Foil)", image=None, slot=0, wear=None),),
    )


def _reader(*lots: Lot, fail_after: int | None = None) -> ExportReader:
    async def read(url: str, on_lot: Callable[[Lot], None], *, timeout_seconds: float) -> int:
        for n, lot in enumerate(lots):
            if n == fail_after:
                raise LisskinsUnavailableError("cut")
            on_lot(lot)
        return LAST

    return read


async def _sync(
    engine: AsyncEngine, *lots: Lot, fail_after: int | None = None
) -> SnapshotResult:
    return await sync_lisskins(
        async_sessionmaker(bind=engine, expire_on_commit=False),
        get_redis(),
        settings=SETTINGS,
        reader=_reader(*lots, fail_after=fail_after),
        now=lambda: NOW,
    )


async def _offers(db: AsyncSession) -> dict[int, tuple[int, str]]:
    db.expire_all()
    rows = (await db.scalars(select(LisskinsOffer))).all()
    return {r.id: (r.price_units, r.skin_item_id) for r in rows}


async def _item(db: AsyncSession, item_id: str) -> SkinItem:
    db.expire_all()
    row = await db.get(SkinItem, item_id)
    assert row is not None
    return row


async def test_lots_map_to_the_catalogue_and_the_ten_cheapest_are_kept(
    db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    item, _ = await make_item_and_rate(db_session)
    lots = [_lot(n, item.market_hash_name, 10_000 + n * 10) for n in range(12, 0, -1)]
    result = await _sync(db_engine, *lots, _lot(99, "Nope | Nothing (Field-Tested)", 1))
    assert (result.refused, result.lots, result.unmapped, result.items) == (False, 13, 1, 1)
    assert sorted(await _offers(db_session)) == list(range(1, 11))
    row = await _item(db_session, item.id)
    assert (row.lisskins_min_units, row.lisskins_count, row.active) == (10_010, 12, True)
    assert row.sell_price_usd is not None
    state = await db_session.get(LisskinsState, 1)
    assert state is not None
    assert (state.snapshot_at, state.synced_at, state.lots) == (
        datetime.fromtimestamp(LAST, UTC),
        NOW,
        13,
    )
    kept = await db_session.get(LisskinsOffer, 1)
    assert kept is not None and kept.stickers == [
        {"name": "Sticker | Crown (Foil)", "image": None, "slot": 0, "wear": None}
    ]


async def test_a_doppler_without_a_phase_maps_by_paint_index(
    db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    name = "★ Karambit | Doppler (Factory New)"
    rows = [
        SkinItem(
            id=new_id(),
            market_hash_name=name,
            phase=phase,
            paint_index=paint,
            slug=f"karambit-doppler-fn-{paint}",
            category="knives",
            search_text="karambit doppler",
        )
        for phase, paint in (("Phase 2", 419), ("Phase 3", 420))
    ]
    db_session.add_all(rows)
    await db_session.commit()
    result = await _sync(
        db_engine, _lot(1, name, 500_000, paint=420), _lot(2, name, 400_000, paint=999)
    )
    assert await _offers(db_session) == {1: (500_000, rows[1].id)}
    assert result.unmapped == 1  # paint 999: no phase, no plain row
    assert (await _item(db_session, rows[0].id)).lisskins_count == 0


async def test_a_second_tick_writes_what_changed_and_deletes_what_left(
    db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    a, _ = await make_item_and_rate(db_session)
    b, _ = await make_item_and_rate(db_session)
    await _sync(
        db_engine,
        _lot(1, a.market_hash_name, 10_000),
        _lot(2, a.market_hash_name, 11_000),
        _lot(3, b.market_hash_name, 9_000),
    )
    await _sync(
        db_engine,
        _lot(2, a.market_hash_name, 10_500),
        _lot(4, a.market_hash_name, 12_000),
        _lot(5, a.market_hash_name, 12_500),
    )
    assert await _offers(db_session) == {
        2: (10_500, a.id),
        4: (12_000, a.id),
        5: (12_500, a.id),
    }
    row_a, row_b = await _item(db_session, a.id), await _item(db_session, b.id)
    assert (row_a.lisskins_min_units, row_a.lisskins_count) == (10_500, 3)
    assert (row_b.lisskins_min_units, row_b.lisskins_count, row_b.active) == (None, 0, False)


async def test_a_collapsed_export_is_refused(
    db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    item, _ = await make_item_and_rate(db_session)
    name = item.market_hash_name
    await _sync(db_engine, *[_lot(n, name, 10_000 + n) for n in range(1, 11)])
    result = await _sync(db_engine, *[_lot(n, name, 9_000) for n in range(1, 5)])
    assert result.refused is True
    assert len(await _offers(db_session)) == 10
    assert (await _item(db_session, item.id)).lisskins_count == 10


async def test_a_truncated_export_changes_nothing(
    db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    item, _ = await make_item_and_rate(db_session)
    name = item.market_hash_name
    await _sync(db_engine, _lot(1, name, 10_000), _lot(2, name, 11_000), _lot(3, name, 12_000))
    before = await _offers(db_session)
    with pytest.raises(LisskinsUnavailableError):
        await _sync(db_engine, _lot(1, name, 5_000), _lot(9, name, 5_000), fail_after=1)
    assert await _offers(db_session) == before
    row = await _item(db_session, item.id)
    assert (row.lisskins_min_units, row.lisskins_count) == (10_000, 3)


async def test_the_cheaper_source_prices_the_card(
    db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    item, _ = await make_item_and_rate(db_session)
    item.skinslink_min_units, item.skinslink_count, item.active = 12_000, 1, True
    await db_session.commit()
    await _sync(db_engine, _lot(1, item.market_hash_name, 11_000))
    row = await _item(db_session, item.id)
    expected = quote(
        11_000,
        rules=await load_rules(db_session, fresh=True),
        category=row.category,
        weapon=row.weapon,
        count_auto=row.stock_count,
        item_pp=row.margin_override_pp,
        fixed_price_usd=row.fixed_price_usd,
        steam_price_units=row.steam_price_units,
    ).price_usd
    assert row.sell_price_usd == expected
```

```python
# apps/api/tests/integration/test_lisskins_rollup.py
"""LIS-SKINS on the catalogue: cleared when off or stale (an item only it stocked goes off
sale), back on sale after a Waxpeer tick, and the sources' tick."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from csmarket.core.config import get_settings
from csmarket.core.redis import get_redis
from csmarket.modules.lisskins.api import rollup
from csmarket.modules.lisskins.models import LisskinsState
from csmarket.modules.skins.models import SkinItem
from csmarket.modules.skins.prices import apply_prices
from csmarket.modules.skins.source_prices import sync_source_prices
from csmarket.modules.skinslink.api import rollup as skinslink_rollup
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.integration.orders_factory import make_item_and_rate

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)
ON = get_settings().model_copy(update={"lisskins_enabled": True, "lisskins_api_key": "k"})


async def _stocked(db: AsyncSession, *, waxpeer: int = 0, snapshot_age_minutes: int = 1) -> str:
    item, _ = await make_item_and_rate(db)
    item.lisskins_min_units, item.lisskins_count = 11_000, 4
    item.count_auto, item.min_auto_units = waxpeer, (12_000 if waxpeer else None)
    item.active = True
    await db.merge(
        LisskinsState(id=1, snapshot_at=NOW - timedelta(minutes=snapshot_age_minutes), lots=4)
    )
    await db.commit()
    return item.id


async def _row(db: AsyncSession, item_id: str) -> SkinItem:
    db.expire_all()
    row = await db.get(SkinItem, item_id)
    assert row is not None
    return row


async def test_a_stale_snapshot_clears_and_takes_a_lisskins_only_item_off_sale(
    db_session: AsyncSession,
) -> None:
    only = await _stocked(db_session, snapshot_age_minutes=21)
    both = await _stocked(db_session, waxpeer=3, snapshot_age_minutes=21)
    await rollup(db_session, settings=ON, now=NOW)
    await db_session.commit()
    a, b = await _row(db_session, only), await _row(db_session, both)
    assert (a.lisskins_min_units, a.lisskins_count, a.active) == (None, 0, False)
    assert (b.lisskins_count, b.active) == (0, True)


async def test_switched_off_clears(db_session: AsyncSession) -> None:
    item_id = await _stocked(db_session)
    await rollup(db_session, settings=get_settings(), now=NOW)
    await db_session.commit()
    assert (await _row(db_session, item_id)).lisskins_count == 0


async def test_a_waxpeer_tick_and_the_skinslink_clear_keep_a_lisskins_item_on_sale(
    db_session: AsyncSession,
) -> None:
    item_id = await _stocked(db_session)
    row = await _row(db_session, item_id)
    row.skinslink_min_units, row.skinslink_count = 12_000, 1  # Skinslink stock, then cleared
    await db_session.commit()
    await apply_prices(db_session, {}, meta=[], at=NOW)  # Waxpeer lists nothing for it
    await skinslink_rollup(db_session, settings=get_settings(), now=NOW)  # Skinslink off
    await db_session.commit()
    assert (await _row(db_session, item_id)).active is True


async def test_a_fresh_snapshot_puts_a_switched_off_item_back_on_sale(
    db_session: AsyncSession,
) -> None:
    item_id = await _stocked(db_session)
    row = await _row(db_session, item_id)
    row.active = False
    await db_session.commit()
    assert await rollup(db_session, settings=ON, now=NOW) == 1
    await db_session.commit()
    assert (await _row(db_session, item_id)).active is True


async def test_the_sources_tick_runs_only_with_a_source_on_or_something_to_clear(
    db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    off = get_settings()
    assert await sync_source_prices(factory, get_redis(), settings=off, at=NOW) is False
    item_id = await _stocked(db_session)
    assert await sync_source_prices(factory, get_redis(), settings=off, at=NOW) is True
    assert (await _row(db_session, item_id)).lisskins_count == 0
    assert await sync_source_prices(factory, get_redis(), settings=ON, at=NOW) is True
```

In `apps/api/tests/unit/test_skins_reprice_cost.py` add:

```python
def test_cost_is_the_cheapest_of_any_number_of_sources() -> None:
    assert cost_units(12_345, None, 11_500) == 11_500
    assert cost_units(None, None, None) is None
    assert cost_units(None, 9_000, 9_000) == 9_000
```

```python
# apps/scheduler/tests/test_lisskins_snapshot.py
"""``lisskins.snapshot``: gated by ``lisskins_active``, stamps the export's time, never raises."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from csmarket.core.config import get_settings
from csmarket.modules.lisskins.api import SnapshotResult
from csmarket_scheduler.jobs import lisskins_snapshot as job
from prometheus_client import REGISTRY

AT = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)


def _settings(monkeypatch: pytest.MonkeyPatch, *, active: bool) -> None:
    update = {"lisskins_enabled": True, "lisskins_api_key": "k"} if active else {}
    s = get_settings().model_copy(update=update)
    monkeypatch.setattr(job, "get_settings", lambda: s)


async def test_inactive_does_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    sync = AsyncMock()
    monkeypatch.setattr(job, "sync_lisskins", sync)
    _settings(monkeypatch, active=False)
    await job.run()
    sync.assert_not_awaited()


async def test_a_good_tick_stamps_the_exports_time(monkeypatch: pytest.MonkeyPatch) -> None:
    result = SnapshotResult(refused=False, lots=3, items=1, snapshot_at=AT)
    monkeypatch.setattr(job, "sync_lisskins", AsyncMock(return_value=result))
    _settings(monkeypatch, active=True)
    await job.run()
    assert REGISTRY.get_sample_value("csmarket_lisskins_snapshot_timestamp_seconds") == (
        AT.timestamp()
    )


async def test_a_failure_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(job, "sync_lisskins", AsyncMock(side_effect=RuntimeError("boom")))
    _settings(monkeypatch, active=True)
    await job.run()


def test_registers_every_5_minutes() -> None:
    scheduler = AsyncIOScheduler()
    job.register(scheduler)
    registered = scheduler.get_job(job.JOB_ID)
    assert registered is not None and registered.trigger.interval.total_seconds() == 300
```

- [ ] **Step 2: Run them**

Run: `cd apps/api && uv run pytest tests/integration/test_lisskins_snapshot.py tests/integration/test_lisskins_rollup.py tests/unit/test_skins_reprice_cost.py -q; cd ../scheduler && uv run pytest tests/test_lisskins_snapshot.py -q`
Expected: FAIL — `ImportError` (`sync_lisskins`, `rollup`, `SnapshotResult`), `cost_units()` takes 2 positional arguments.

- [ ] **Step 3: Write `lisskins/snapshot.py`**

```python
"""The snapshot of LIS-SKINS' instant lots (spec 2026-10-07 §3).

:func:`load_index` maps a lot's name to our catalogue as the Skinslink mirror does
(``skins.canonical_name``), plus one rule of its own: a Doppler-family name without a phase
is placed by ``item_paint_index`` against ``skin_items.paint_index`` (each phase is its own
paint). :class:`Collector` is fed every sellable lot of the export and keeps, per catalogue
item, how many there are and the :data:`KEEP` cheapest; unmapped names are counted and
dropped, so memory stays at ~10 lots per item whatever the export's size.
:func:`apply_snapshot` writes it in the caller's transaction: the offers that changed, the
ones that left, the roll-up onto ``skin_items`` and ``lisskins_state`` — or nothing, when the
export holds under :data:`MIN_SHARE` of the previous tick's lots.
"""

from __future__ import annotations

import heapq
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.config import Settings
from csmarket.core.logging import get_logger
from csmarket.modules.lisskins.export import Lot
from csmarket.modules.lisskins.models import LisskinsOffer, LisskinsState
from csmarket.modules.skins.api import SkinItem, canonical_name

log = get_logger("csmarket.lisskins.snapshot")

#: Lots kept per catalogue item.
KEEP = 10
#: A tick whose export has fewer sellable lots than this share of the last applied one is
#: refused (a cut or broken export must not read as a sold-out market).
MIN_SHARE = 0.5
#: Rows per bulk statement (asyncpg caps bind parameters at 32 767).
_BATCH = 1000
_COLUMNS = (
    "skin_item_id",
    "price_units",
    "float_value",
    "paint_seed",
    "asset_id",
    "inspect_url",
    "stickers",
    "updated_at",
)


class CatalogueIndex:
    """Our ``skin_items.id`` for a LIS-SKINS name (and paint index)."""

    def __init__(self, rows: Iterable[tuple[str, str, str, int | None]]) -> None:
        self._plain: dict[tuple[str, str], str] = {}
        self._painted: dict[tuple[str, int], str] = {}
        self._seen: dict[tuple[str, int | None], str | None] = {}
        for item_id, name, phase, paint in rows:
            self._plain[(name, phase)] = item_id
            if phase and paint is not None:
                self._painted[(name, paint)] = item_id

    def item_for(self, name: str, paint_index: int | None) -> str | None:
        """The catalogue item, or ``None`` when we do not sell it (memoised per name)."""
        key = (name, paint_index)
        if key not in self._seen:
            self._seen[key] = self._lookup(name, paint_index)
        return self._seen[key]

    def _lookup(self, name: str, paint_index: int | None) -> str | None:
        base, inline = canonical_name(name)
        if inline:
            return self._plain.get((base, inline))
        if paint_index is not None and (hit := self._painted.get((base, paint_index))):
            return hit
        return self._plain.get((base, ""))


async def load_index(db: AsyncSession) -> CatalogueIndex:
    """Every catalogue row's name, phase and paint index."""
    rows = await db.execute(
        select(SkinItem.id, SkinItem.market_hash_name, SkinItem.phase, SkinItem.paint_index)
    )
    return CatalogueIndex((r[0], r[1], r[2], r[3]) for r in rows.all())


@dataclass
class _Kept:
    """One item's lots: how many, and a heap of the cheapest (dearest at the root)."""

    count: int = 0
    #: ``(-price, -lot id, -arrival, lot)``: the root is the one to drop next.
    heap: list[tuple[int, int, int, Lot]] = field(default_factory=list)


class Collector:
    """Fed every sellable lot of one export; keeps what the snapshot writes."""

    def __init__(self, index: CatalogueIndex, *, keep: int = KEEP) -> None:
        self._index = index
        self._keep = keep
        self.lots = 0
        self.unmapped = 0
        self.items: dict[str, _Kept] = {}

    def add(self, lot: Lot) -> None:
        """Count ``lot`` and keep it if it is among its item's cheapest."""
        self.lots += 1
        item_id = self._index.item_for(lot.name, lot.paint_index)
        if item_id is None:
            self.unmapped += 1
            return
        kept = self.items.setdefault(item_id, _Kept())
        kept.count += 1
        entry = (-lot.price_units, -lot.id, -self.lots, lot)
        if len(kept.heap) < self._keep:
            heapq.heappush(kept.heap, entry)
        elif entry[:3] > kept.heap[0][:3]:
            heapq.heapreplace(kept.heap, entry)

    def cheapest(self, item_id: str) -> list[Lot]:
        """The item's kept lots, cheapest first (then by id)."""
        return [e[3] for e in sorted(self.items[item_id].heap, key=lambda e: e[:3], reverse=True)]

    def summary(self) -> dict[str, tuple[int, int]]:
        """``(cheapest units, lot count)`` per item."""
        return {
            item_id: (-max(e[0] for e in kept.heap), kept.count)
            for item_id, kept in self.items.items()
        }


@dataclass(frozen=True)
class SnapshotResult:
    """What one tick did."""

    refused: bool
    lots: int
    unmapped: int = 0
    items: int = 0
    written: int = 0
    removed: int = 0
    snapshot_at: datetime | None = None


# Any: one row of ``lisskins_offers`` for a bulk insert.
def _row(item_id: str, lot: Lot, now: datetime) -> dict[str, Any]:
    return {
        "id": lot.id,
        "skin_item_id": item_id,
        "price_units": lot.price_units,
        "float_value": lot.float_value,
        "paint_seed": lot.paint_seed,
        "asset_id": lot.asset_id,
        "inspect_url": lot.inspect_url,
        "stickers": [asdict(s) for s in lot.stickers],
        "updated_at": now,
    }


async def _write_offers(db: AsyncSession, collected: Collector, *, now: datetime) -> tuple[int, int]:
    """Upsert the kept lots that are new or moved; delete the ones that left."""
    have = {
        r[0]: (r[1], r[2])
        for r in (
            await db.execute(
                select(LisskinsOffer.id, LisskinsOffer.price_units, LisskinsOffer.skin_item_id)
            )
        ).all()
    }
    # One statement may touch a row once: a lot id the export lists twice is written once.
    rows = list(
        {
            lot.id: _row(item_id, lot, now)
            for item_id in collected.items
            for lot in collected.cheapest(item_id)
        }.values()
    )
    changed = [r for r in rows if have.get(r["id"]) != (r["price_units"], r["skin_item_id"])]
    for start in range(0, len(changed), _BATCH):
        stmt = pg_insert(LisskinsOffer).values(changed[start : start + _BATCH])
        await db.execute(
            stmt.on_conflict_do_update(
                index_elements=[LisskinsOffer.id], set_={c: stmt.excluded[c] for c in _COLUMNS}
            )
        )
    gone = list(have.keys() - {r["id"] for r in rows})
    for start in range(0, len(gone), _BATCH):
        await db.execute(
            delete(LisskinsOffer).where(LisskinsOffer.id.in_(gone[start : start + _BATCH]))
        )
    return len(changed), len(gone)


async def _write_rollup(db: AsyncSession, collected: Collector) -> None:
    """``lisskins_min_units`` / ``lisskins_count`` for every item with lots; cleared (and
    ``active`` re-derived from the other sources) for those that have none now."""
    want = collected.summary()
    have = {
        r[0]: (r[1], r[2])
        for r in (
            await db.execute(
                select(SkinItem.id, SkinItem.lisskins_min_units, SkinItem.lisskins_count).where(
                    SkinItem.lisskins_count > 0
                )
            )
        ).all()
    }
    updates = [
        {"id": item_id, "lisskins_min_units": m, "lisskins_count": n, "active": True}
        for item_id, (m, n) in want.items()
        if have.get(item_id) != (m, n)
    ]
    for start in range(0, len(updates), _BATCH):
        await db.execute(update(SkinItem), updates[start : start + _BATCH])
    gone = list(have.keys() - want.keys())
    for start in range(0, len(gone), _BATCH):
        await db.execute(
            update(SkinItem)
            .where(SkinItem.id.in_(gone[start : start + _BATCH]))
            .values(
                lisskins_min_units=None,
                lisskins_count=0,
                active=(SkinItem.count_auto > 0) | (SkinItem.skinslink_count > 0),
            )
            .execution_options(synchronize_session=False)
        )


async def apply_snapshot(
    db: AsyncSession, collected: Collector, *, snapshot_at: datetime, now: datetime
) -> SnapshotResult:
    """Write the collected export (never commits); refused — nothing written — when it holds
    fewer than :data:`MIN_SHARE` of the previous tick's lots."""
    state = await db.get(LisskinsState, 1) or LisskinsState(id=1, lots=0)
    if state.lots and collected.lots < state.lots * MIN_SHARE:
        log.warning("lisskins.snapshot.refused", lots=collected.lots, before=state.lots)
        return SnapshotResult(refused=True, lots=collected.lots, snapshot_at=snapshot_at)
    written, removed = await _write_offers(db, collected, now=now)
    await _write_rollup(db, collected)
    state.snapshot_at, state.synced_at, state.lots = snapshot_at, now, collected.lots
    db.add(state)
    return SnapshotResult(
        refused=False,
        lots=collected.lots,
        unmapped=collected.unmapped,
        items=len(collected.items),
        written=written,
        removed=removed,
        snapshot_at=snapshot_at,
    )


async def snapshot_fresh(db: AsyncSession, *, settings: Settings, now: datetime) -> bool:
    """The applied export was made within ``lisskins_stale_minutes``."""
    made = await db.scalar(select(LisskinsState.snapshot_at).where(LisskinsState.id == 1))
    return made is not None and now - made <= timedelta(minutes=settings.lisskins_stale_minutes)


__all__ = [
    "KEEP",
    "MIN_SHARE",
    "CatalogueIndex",
    "Collector",
    "SnapshotResult",
    "apply_snapshot",
    "load_index",
    "snapshot_fresh",
]
```

- [ ] **Step 4: Write `lisskins/rollup.py`**

```python
"""LIS-SKINS on the catalogue, kept honest every price tick (spec 2026-10-07 §4).

The snapshot writes ``lisskins_min_units`` / ``lisskins_count``. Each price tick then: while
LIS-SKINS is on and its snapshot fresh, an item with LIS-SKINS lots is on sale (a Waxpeer
tick may have switched it off); otherwise every LIS-SKINS roll-up is cleared and ``active``
re-derived from the other sources. ``skins.repricing`` then prices from the cheapest side.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.config import Settings
from csmarket.modules.lisskins.snapshot import snapshot_fresh
from csmarket.modules.skins.api import SkinItem


def _rowcount(result: object) -> int:
    """``rowcount`` lives on CursorResult; async ``execute`` is typed as Result."""
    return int(getattr(result, "rowcount", 0) or 0)


async def rollup(db: AsyncSession, *, settings: Settings, now: datetime) -> int:
    """Apply the rule above; returns the rows it changed. Never commits."""
    stmt = update(SkinItem).where(SkinItem.lisskins_count > 0)
    if settings.lisskins_active and await snapshot_fresh(db, settings=settings, now=now):
        stmt = stmt.where(SkinItem.active.is_(False)).values(active=True)
    else:
        stmt = stmt.values(
            lisskins_min_units=None,
            lisskins_count=0,
            active=(SkinItem.count_auto > 0) | (SkinItem.skinslink_count > 0),
        )
    result = await db.execute(stmt.execution_options(synchronize_session=False))
    return _rowcount(result)


__all__ = ["rollup"]
```

`lisskins/api.py` re-exports `KEEP`, `CatalogueIndex`, `Collector`, `SnapshotResult`, `apply_snapshot`, `load_index`, `snapshot_fresh`, `rollup`, plus `ExportReader`, `Lot`, `Sticker`, `read_export`, `to_units` from Task 2.

- [ ] **Step 5: Keep every source's stock on sale, and price from the cheapest**

`skinslink/rollup.py::_clear` — `active=SkinItem.count_auto > 0` becomes `active=(SkinItem.count_auto > 0) | (SkinItem.lisskins_count > 0)`.

`skins/prices.py::apply_prices` — in the deactivation `update`, `active=SkinItem.skinslink_count > 0` becomes `active=(SkinItem.skinslink_count > 0) | (SkinItem.lisskins_count > 0)` and its comment says "Skinslink or LIS-SKINS stock keeps the item on sale (their roll-ups own that side)". In `sync_prices`, import `from csmarket.modules.lisskins.api import rollup as lisskins_rollup` and `from csmarket.modules.skinslink.api import rollup as skinslink_rollup`, and replace the single roll-up call with:

```python
        await skinslink_rollup(db, settings=get_settings(), now=at)
        await lisskins_rollup(db, settings=get_settings(), now=at)
```

Delete `_clear_waxpeer_stock` and `sync_skinslink_prices` from `prices.py` (and from its `__all__`); they move below.

`skins/repricing.py`:

```python
def cost_units(*units: int | None) -> int | None:
    """The cheapest source's units among those with stock; ``None`` with none."""
    present = [u for u in units if u is not None]
    return min(present) if present else None
```

In `reprice_rows` add `SkinItem.lisskins_min_units, SkinItem.lisskins_count,` to the `select`, and:

```python
        units = cost_units(row.min_auto_units, row.skinslink_min_units, row.lisskins_min_units)
        ...
                # Liquidity counts every source's stock.
                count_auto=row.count_auto + row.skinslink_count + row.lisskins_count,
```

- [ ] **Step 6: Write `skins/source_prices.py`**

```python
"""The non-Waxpeer sources on the catalogue (specs 2026-10-06, 2026-10-07).

:func:`sync_lisskins` — the ``lisskins.snapshot`` job: stream LIS-SKINS' export with no
transaction open (it takes minutes), then in one transaction under the pricing lock write
the snapshot, roll it up and reprice. :func:`sync_source_prices` — the ``sources.prices``
job (was ``skinslink.prices``): roll Skinslink and LIS-SKINS up and reprice without waiting
for a Waxpeer tick, so their prices appear — and leave when a source goes stale or is
switched off — on their own.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from csmarket.core import clock
from csmarket.core.config import Settings
from csmarket.core.logging import get_logger
from csmarket.modules.lisskins.api import (
    Collector,
    ExportReader,
    SnapshotResult,
    apply_snapshot,
    load_index,
    read_export,
)
from csmarket.modules.lisskins.api import rollup as lisskins_rollup
from csmarket.modules.skins.cachekeys import bump_catalog_version
from csmarket.modules.skins.models import SkinItem
from csmarket.modules.skins.repricing import lock_pricing, reprice_rows
from csmarket.modules.skins.settings import load_rules
from csmarket.modules.skinslink.api import rollup as skinslink_rollup

log = get_logger("csmarket.skins.source_prices")


async def sync_lisskins(
    session_factory: async_sessionmaker[AsyncSession],
    redis: Redis,
    *,
    settings: Settings,
    reader: ExportReader = read_export,
    now: Callable[[], datetime] = clock.now,
) -> SnapshotResult:
    """One snapshot tick (see the module docstring).

    Raises:
        LisskinsUnavailableError: The export could not be read whole — nothing is written.
    """
    async with session_factory() as db:
        index = await load_index(db)
        await db.commit()
    collected = Collector(index)
    last_update = await reader(
        settings.lisskins_export_url,
        collected.add,
        timeout_seconds=settings.lisskins_request_timeout_seconds,
    )
    at = now()
    async with session_factory() as db:
        await lock_pricing(db)
        result = await apply_snapshot(
            db, collected, snapshot_at=datetime.fromtimestamp(last_update, UTC), now=at
        )
        if result.refused:
            await db.rollback()
            return result
        await lisskins_rollup(db, settings=settings, now=at)
        await reprice_rows(db, await load_rules(db, fresh=True))
        await db.commit()
    await bump_catalog_version(redis)
    log.info(
        "lisskins.snapshot.applied",
        lots=result.lots,
        unmapped=result.unmapped,
        items=result.items,
        written=result.written,
        removed=result.removed,
    )
    return result


async def _clear_waxpeer_stock(db: AsyncSession) -> None:
    """Waxpeer buying is off: forget the stock an earlier Waxpeer tick wrote."""
    await db.execute(
        update(SkinItem)
        .where(SkinItem.count_auto > 0)
        .values(min_auto_units=None, count_auto=0, cheapest_auto=[], price_hash=None)
        .execution_options(synchronize_session=False)
    )


async def sync_source_prices(
    session_factory: async_sessionmaker[AsyncSession],
    redis: Redis,
    *,
    settings: Settings,
    at: datetime,
) -> bool:
    """Roll Skinslink and LIS-SKINS up and reprice; runs while either is on, or while an
    earlier roll-up of either is still on the catalogue to clear.

    Returns:
        Whether it repriced.
    """
    async with session_factory() as db:
        if not (settings.skinslink_active or settings.lisskins_active):
            left = await db.scalar(
                select(SkinItem.id)
                .where((SkinItem.skinslink_count > 0) | (SkinItem.lisskins_count > 0))
                .limit(1)
            )
            if left is None:
                return False
        await lock_pricing(db)
        if not settings.waxpeer_buy_enabled:
            await _clear_waxpeer_stock(db)
        await skinslink_rollup(db, settings=settings, now=at)
        await lisskins_rollup(db, settings=settings, now=at)
        await reprice_rows(db, await load_rules(db, fresh=True))
        await db.commit()
    await bump_catalog_version(redis)
    return True


__all__ = ["sync_lisskins", "sync_source_prices"]
```

`core/metrics.py`:

```python
LISSKINS_SNAPSHOT_TIMESTAMP = Gauge(
    "csmarket_lisskins_snapshot_timestamp_seconds",
    "The LIS-SKINS export's own time of the last applied snapshot (alert: LisskinsSnapshotStale).",
)


def set_lisskins_snapshot(at_unix: float) -> None:
    """Stamp an applied LIS-SKINS snapshot with its export's time. Never raises."""
    try:
        LISSKINS_SNAPSHOT_TIMESTAMP.set(at_unix)
    except Exception as exc:  # noqa: BLE001 -- Rule 2 in the module docstring
        log.warning(
            "metrics.set_failed",
            metric="csmarket_lisskins_snapshot_timestamp_seconds",
            error=type(exc).__name__,
        )
```

- [ ] **Step 7: The scheduler jobs**

```bash
git mv apps/scheduler/src/csmarket_scheduler/jobs/skinslink_prices.py apps/scheduler/src/csmarket_scheduler/jobs/source_prices.py
git mv apps/scheduler/tests/test_skinslink_prices.py apps/scheduler/tests/test_source_prices.py
```

In `source_prices.py`: `JOB_ID = "sources.prices"`, the docstring says "roll Skinslink's and LIS-SKINS' stock onto the catalogue and reprice (`skins.source_prices.sync_source_prices`)", it imports and awaits `sync_source_prices` (same arguments), log keys `sources.prices.failed`. In its test, replace `sync_skinslink_prices` with `sync_source_prices` and `skinslink_prices` with `source_prices`. In `test_main.py` replace `"skinslink.prices"` with `"sources.prices"` and add `"lisskins.snapshot"` after it; in `main.py` import `lisskins_snapshot, source_prices` instead of `skinslink_prices`, and register `source_prices.register(scheduler)` then `lisskins_snapshot.register(scheduler)` where `skinslink_prices` was. In `apps/api/tests/integration/test_skinslink_rollup.py` and `test_waxpeer_buy_off.py` import `sync_source_prices` from `csmarket.modules.skins.source_prices` and call it under the new name.

`jobs/lisskins_snapshot.py`:

```python
"""Every 5 minutes: snapshot LIS-SKINS' instant lots (``skins.source_prices.sync_lisskins``).

Skipped unless ``lisskins_active``. ``max_instances=1`` and ``coalesce=True``: a slow
download (~855 MB) is never joined by the next tick. A failure is logged by type only and
the last snapshot stays; ``LisskinsSnapshotStale`` notices when it ages.
"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from csmarket.core.config import get_settings
from csmarket.core.db import get_session_factory
from csmarket.core.logging import get_logger
from csmarket.core.metrics import set_lisskins_snapshot
from csmarket.core.redis import get_redis
from csmarket.modules.skins.source_prices import sync_lisskins

from csmarket_scheduler.startup import first_run_after

log = get_logger("csmarket.scheduler.lisskins_snapshot")

JOB_ID = "lisskins.snapshot"
INTERVAL_SECONDS = 300


async def run() -> None:
    """One tick. Never raises."""
    settings = get_settings()
    if not settings.lisskins_active:
        return
    try:
        result = await sync_lisskins(get_session_factory(), get_redis(), settings=settings)
    except Exception as exc:  # noqa: BLE001 -- a tick never raises; the next one retries
        log.warning("lisskins.snapshot.failed", error=type(exc).__name__)
        return
    if not result.refused and result.snapshot_at is not None:
        set_lisskins_snapshot(result.snapshot_at.timestamp())


def register(scheduler: AsyncIOScheduler) -> None:
    """Every :data:`INTERVAL_SECONDS`; first run 320 s after start."""
    scheduler.add_job(
        run,
        trigger="interval",
        seconds=INTERVAL_SECONDS,
        id=JOB_ID,
        next_run_time=first_run_after(320),
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    log.info("scheduler.job.registered", job=JOB_ID, interval_seconds=INTERVAL_SECONDS)
```

- [ ] **Step 8: Run the tests and the gates**

Run: `cd apps/api && uv run pytest tests/integration/test_lisskins_snapshot.py tests/integration/test_lisskins_rollup.py tests/integration/test_skinslink_rollup.py tests/integration/test_waxpeer_buy_off.py tests/integration/test_skins_price_sync.py tests/integration/test_skins_reprice.py tests/unit/test_skins_reprice_cost.py -q && cd ../scheduler && uv run pytest tests -q && cd ../.. && make lint typecheck`
Expected: PASS; clean.

- [ ] **Step 9: Commit**

```bash
git add apps/api/src apps/api/tests apps/scheduler
git commit -m "feat(api/lisskins): snapshot LIS-SKINS' instant lots every 5 minutes; cards cost the cheapest source" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: LIS-SKINS offers on the item page; one asset shown once; every source in the counts

**Files:**

- Modify: `apps/api/src/csmarket/modules/skins/offers.py` (the third source, `TIE_ORDER`, dedupe by asset)
- Create: `apps/api/src/csmarket/modules/lisskins/offers.py`; modify `lisskins/api.py` (`offers_for`)
- Modify: `apps/api/src/csmarket/modules/skins/routes.py:124,271,291,341` (`item.stock_count`), `:325-335` (LIS-SKINS offers join the list)
- Modify: `apps/api/src/csmarket/modules/skins/service.py:135,144` (the `popular` sort counts every source)
- Modify: `apps/api/src/csmarket/modules/skins/api.py` (export `TIE_ORDER`)
- Test: `apps/api/tests/unit/test_skins_offers.py`, `apps/api/tests/integration/test_lisskins_offers.py`, `apps/api/tests/integration/test_lisskins_listings_route.py`

**Interfaces:**

- Consumes: `LisskinsOffer`, `snapshot_fresh` (Tasks 3–4); `SkinItem.stock_count` (Task 3).
- Produces in `skins/offers.py`: `Source = Literal["waxpeer", "skinslink", "lisskins"]`; `offer_id_of("lisskins", 125345) == "ls:125345"`; `parse_offer_id("ls:125345") == ("lisskins", "125345")` (1–20 digits); `TIE_ORDER: dict[Source, int] = {"waxpeer": 0, "skinslink": 1, "lisskins": 2}`; `merge_offers(*groups)` sorts by `(price_units, TIE_ORDER[source], offer_id)` and drops a later offer whose `asset_id` an earlier one carried. `Offer.asset_id` is documented as "the Steam asset: Skinslink's offer id, LIS-SKINS' `item_asset_id`".
- Produces in `lisskins/offers.py`: `async offers_for(db, skin_item_id: str, *, settings, now) -> list[Offer]` (by price; `[]` while off, keyless or stale).

- [ ] **Step 1: Write the failing tests**

In `apps/api/tests/unit/test_skins_offers.py` add:

```python
def test_lisskins_ids_round_trip() -> None:
    assert offer_id_of("lisskins", 125345) == "ls:125345"
    assert parse_offer_id("ls:125345") == ("lisskins", "125345")


@pytest.mark.parametrize("bad", ["ls:", "ls:abc", "ls:1a", "ls:-1", "ls:" + "1" * 21])
def test_bad_lisskins_ids_are_refused(bad: str) -> None:
    with pytest.raises(ValueError, match="offer id"):
        parse_offer_id(bad)


def test_ties_go_waxpeer_then_skinslink_then_lisskins() -> None:
    merged = merge_offers(
        [_o("lisskins", 1000, "5")], [_o("skinslink", 1000, "8")], [_o("waxpeer", 1000, "1")]
    )
    assert [o.offer_id for o in merged] == ["wx:1", "sl:8", "ls:5"]


def test_one_asset_in_two_sources_is_shown_once_at_the_cheaper() -> None:
    sl = replace(_o("skinslink", 1200, "777"), asset_id="777")
    ls = replace(_o("lisskins", 1100, "5"), asset_id="777")
    other = replace(_o("lisskins", 1300, "6"), asset_id="778")
    assert [o.offer_id for o in merge_offers([sl], [ls, other])] == ["ls:5", "ls:6"]
    tie = replace(ls, price_units=1200)
    assert [o.offer_id for o in merge_offers([tie], [sl])] == ["sl:777"]
```

(add `from dataclasses import replace` to the imports; the existing `test_merge_sorts_by_price_then_waxpeer_first` stays green.)

```python
# apps/api/tests/integration/test_lisskins_offers.py
"""LIS-SKINS offers come from the snapshot (no external call): by price, none when off or
stale, stickers as the item page shows them."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from csmarket.core.config import get_settings
from csmarket.modules.lisskins.api import offers_for
from csmarket.modules.lisskins.models import LisskinsOffer, LisskinsState
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.orders_factory import make_item_and_rate

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)
ON = get_settings().model_copy(update={"lisskins_enabled": True, "lisskins_api_key": "k"})


async def _seed(db: AsyncSession, *, age_minutes: int = 1) -> str:
    item, _ = await make_item_and_rate(db)
    db.add_all(
        [
            LisskinsOffer(id=6, skin_item_id=item.id, price_units=13_000, asset_id="778"),
            LisskinsOffer(
                id=5,
                skin_item_id=item.id,
                price_units=11_000,
                asset_id="777",
                inspect_url="steam://rungame/730/x",
                stickers=[
                    {"name": "Sticker | Crown (Foil)", "image": "https://x/y.png", "slot": 2, "wear": 0.5},
                    {"name": 3},
                ],
            ),
            LisskinsState(id=1, snapshot_at=NOW - timedelta(minutes=age_minutes), lots=2),
        ]
    )
    await db.commit()
    return item.id


async def test_offers_by_price_with_their_details(db_session: AsyncSession) -> None:
    item_id = await _seed(db_session)
    offers = await offers_for(db_session, item_id, settings=ON, now=NOW)
    assert [(o.offer_id, o.source, o.price_units, o.asset_id) for o in offers] == [
        ("ls:5", "lisskins", 11_000, "777"),
        ("ls:6", "lisskins", 13_000, "778"),
    ]
    assert offers[0].stickers == [
        {"name": "Sticker | Crown (Foil)", "image": "https://x/y.png", "slot": 2, "wear": 0.5}
    ]
    assert offers[0].inspect_url == "steam://rungame/730/x"


async def test_none_when_stale_or_off(db_session: AsyncSession) -> None:
    item_id = await _seed(db_session, age_minutes=21)
    assert await offers_for(db_session, item_id, settings=ON, now=NOW) == []
    assert await offers_for(db_session, item_id, settings=get_settings(), now=NOW) == []
```

```python
# apps/api/tests/integration/test_lisskins_listings_route.py
"""``GET /skins/{slug}/listings`` and the item page with LIS-SKINS on: its lots join the
list, one Steam asset shows once, sticker images only from Steam's CDN, counts add up."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from csmarket.core import config as cfg
from csmarket.core.ids import new_id
from csmarket.modules.fx.api import record_snapshot
from csmarket.modules.lisskins.models import LisskinsOffer, LisskinsState
from csmarket.modules.skins.models import SkinItem
from csmarket.modules.skinslink.models import SkinslinkItem, SkinslinkState
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio

SLUG = "ak-47-redline-ft"
STEAM_IMAGE = "https://community.cloudflare.steamstatic.com/economy/image/abc"


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for name, value in {
        "WAXPEER_BUY_ENABLED": "false",
        "SKINSLINK_ENABLED": "true",
        "SKINSLINK_API_KEY": "k",
        "SKINSLINK_SECRET": "s",
        "LISSKINS_ENABLED": "true",
        "LISSKINS_API_KEY": "k",
    }.items():
        monkeypatch.setenv(f"CSMARKET_{name}", value)
    cfg.get_settings.cache_clear()
    yield
    cfg.get_settings.cache_clear()


@pytest.fixture
async def item(db_session: AsyncSession) -> SkinItem:
    await record_snapshot(db_session, rate=Decimal("12700"), source="cbu")
    row = SkinItem(
        id=new_id(),
        market_hash_name="AK-47 | Redline (Field-Tested)",
        phase="",
        slug=SLUG,
        category="rifles",
        weapon="AK-47",
        search_text=SLUG,
        active=True,
        cheapest_auto=[],
        skinslink_min_units=12_000,
        skinslink_count=1,
        lisskins_min_units=11_000,
        lisskins_count=7,
    )
    at = datetime.now(UTC)
    db_session.add_all(
        [
            row,
            SkinslinkState(id=1, cursor="c", mirror_synced_at=at),
            LisskinsState(id=1, snapshot_at=at, lots=2),
            SkinslinkItem(
                id="777",
                market_hash_name=row.market_hash_name,
                phase="",
                price_units=12_000,
                skin_item_id=row.id,
            ),
            LisskinsOffer(
                id=5,
                skin_item_id=row.id,
                price_units=11_000,
                asset_id="777",
                stickers=[{"name": "Sticker | A", "image": "https://lis-skins.com/a.png", "slot": 0, "wear": None}],
            ),
            LisskinsOffer(
                id=6,
                skin_item_id=row.id,
                price_units=13_000,
                asset_id="778",
                stickers=[{"name": "Sticker | B", "image": STEAM_IMAGE, "slot": 1, "wear": 0.1}],
            ),
        ]
    )
    await db_session.commit()
    return row


async def test_lisskins_lots_join_the_list_and_one_asset_shows_once(
    integration_client: AsyncClient, item: SkinItem
) -> None:
    r = await integration_client.get(f"/api/v1/skins/{SLUG}/listings")
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert [i["listing_id"] for i in items] == ["ls:5", "ls:6"]  # sl:777 is the same asset
    assert items[0]["stickers"][0]["image"] is None  # LIS-SKINS' own CDN never reaches a browser
    assert items[1]["stickers"][0]["image"] is not None


async def test_the_card_counts_every_source(
    integration_client: AsyncClient, item: SkinItem
) -> None:
    r = await integration_client.get(f"/api/v1/skins/{SLUG}")
    assert r.status_code == 200, r.text
    assert r.json()["count"] == 8  # 0 Waxpeer + 1 Skinslink + 7 LIS-SKINS
```

- [ ] **Step 2: Run them**

Run: `cd apps/api && uv run pytest tests/unit/test_skins_offers.py tests/integration/test_lisskins_offers.py tests/integration/test_lisskins_listings_route.py -q`
Expected: FAIL — `KeyError: 'lisskins'` in `offer_id_of`, `ImportError: offers_for`, listings without `ls:` ids.

- [ ] **Step 3: Implement**

`skins/offers.py` — module docstring adds "or `ls:<LIS-SKINS skin id>`"; then:

```python
Source = Literal["waxpeer", "skinslink", "lisskins"]
_PREFIX: dict[str, Source] = {"wx": "waxpeer", "sl": "skinslink", "ls": "lisskins"}
_PREFIX_OF: dict[Source, str] = {"waxpeer": "wx", "skinslink": "sl", "lisskins": "ls"}
#: Waxpeer's listing ids and LIS-SKINS' skin ids are integers.
_DIGITS = re.compile(r"[0-9]{1,20}")
...
_PATTERN: dict[Source, re.Pattern[str]] = {
    "waxpeer": _DIGITS,
    "skinslink": _SKINSLINK_ID,
    "lisskins": _DIGITS,
}
#: Who is listed first at one price: Waxpeer (instant), Skinslink, then LIS-SKINS.
TIE_ORDER: dict[Source, int] = {"waxpeer": 0, "skinslink": 1, "lisskins": 2}
```

In `parse_offer_id` the check becomes `if not sep or source is None or not _PATTERN[source].fullmatch(raw):` (drop `_WAXPEER_ID`, use `_DIGITS`). `merge_offers`:

```python
def merge_offers(*groups: Sequence[Offer]) -> list[Offer]:
    """Every group's offers by price, ties by :data:`TIE_ORDER`; a Steam asset two sources
    list is shown once — its first (cheapest, then tie-winning) offer."""
    ordered = sorted(
        (o for group in groups for o in group),
        key=lambda o: (o.price_units, TIE_ORDER[o.source], o.offer_id),
    )
    seen: set[str] = set()
    merged: list[Offer] = []
    for offer in ordered:
        if offer.asset_id is not None:
            if offer.asset_id in seen:
                continue
            seen.add(offer.asset_id)
        merged.append(offer)
    return merged
```

`__all__` adds `"TIE_ORDER"`; `skins/api.py` re-exports it.

`lisskins/offers.py`:

```python
"""LIS-SKINS' offers of one catalogue item, read from the snapshot (no external call)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.config import Settings
from csmarket.modules.lisskins.models import LisskinsOffer
from csmarket.modules.lisskins.snapshot import snapshot_fresh
from csmarket.modules.skins.api import Offer, offer_id_of


# Any: one stored sticker object (``export.Sticker`` as a dict).
def _sticker(raw: dict[str, Any]) -> dict[str, Any] | None:
    """A sticker as ``Offer.stickers`` carries it; the image is filtered on the way out
    (``skins.images.steam_image_only``)."""
    name, image, slot, wear = raw.get("name"), raw.get("image"), raw.get("slot"), raw.get("wear")
    if not isinstance(name, str):
        return None
    return {
        "name": name,
        "image": image if isinstance(image, str) else None,
        "slot": slot if isinstance(slot, int) and not isinstance(slot, bool) else None,
        "wear": float(wear) if isinstance(wear, int | float) and not isinstance(wear, bool) else None,
    }


async def offers_for(
    db: AsyncSession, skin_item_id: str, *, settings: Settings, now: datetime
) -> list[Offer]:
    """The item's LIS-SKINS lots by price; none while off, keyless or stale."""
    if not settings.lisskins_active or not await snapshot_fresh(db, settings=settings, now=now):
        return []
    rows = (
        await db.scalars(
            select(LisskinsOffer)
            .where(LisskinsOffer.skin_item_id == skin_item_id)
            .order_by(LisskinsOffer.price_units, LisskinsOffer.id)
        )
    ).all()
    return [
        Offer(
            offer_id=offer_id_of("lisskins", r.id),
            source="lisskins",
            price_units=r.price_units,
            float_value=None if r.float_value is None else float(r.float_value),
            paint_seed=r.paint_seed,
            stickers=[s for raw in r.stickers if isinstance(raw, dict) and (s := _sticker(raw))],
            inspect_url=r.inspect_url,
            asset_id=r.asset_id,
        )
        for r in rows
    ]


__all__ = ["offers_for"]
```

`skins/routes.py`: import `from csmarket.modules.lisskins.api import offers_for as lisskins_offers` and `from csmarket.modules.skinslink.api import offers_for as skinslink_offers`; in `get_listings`:

```python
    # Skinslink's and LIS-SKINS' offers come from our own tables (no external call); this
    # route composes the sources — ``skins`` itself never imports them.
    at = now()
    extra = [
        *await skinslink_offers(db, item.id, settings=settings, now=at),
        *await lisskins_offers(db, item.id, settings=settings, now=at),
    ]
```

and every `item.count_auto + item.skinslink_count` / `m.count_auto + m.skinslink_count` in the file becomes `item.stock_count` / `m.stock_count`. `skins/service.py`: `_sort_column` returns `SkinItem.count_auto + SkinItem.skinslink_count + SkinItem.lisskins_count`; `_sort_value` returns `item.stock_count`.

- [ ] **Step 4: Run tests and gates**

Run: `cd apps/api && uv run pytest tests/unit/test_skins_offers.py tests/integration/test_lisskins_offers.py tests/integration/test_lisskins_listings_route.py tests/integration/test_skins_listings_route.py tests/integration/test_skinslink_offers.py -q && cd ../.. && make lint typecheck && make gen-api`
Expected: PASS; clean; `git status` shows no OpenAPI drift (no schema changed).

- [ ] **Step 5: Commit**

```bash
git add apps/api/src apps/api/tests
git commit -m "feat(api/skins): LIS-SKINS lots on the item page; one Steam asset shown once; counts add every source" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Checkout re-checks a LIS-SKINS lot live (ADR-0012)

Decisions: only the **chosen** offer is checked, and only when it is an `ls:` offer — one call per `POST /orders`; a lot in neither list of the answer reads "unknown" (snapshot price, the worker's `max_price` guards); the budget is a constant (`BUDGET_PER_MINUTE = 100`, half the key's 200/min, the rest left to the reconcile and the buys), not a setting; `POST /orders` (`/v1/orders`) is already in the `ApiHighLatency` / `ApiWaxpeerLatency` handler regexes, so only their comment changes.

**Files:**

- Create: `apps/api/src/csmarket/modules/lisskins/availability.py`; modify `lisskins/api.py` (`live_price`, `recheck_chosen`)
- Modify: `apps/api/src/csmarket/modules/orders/checkout.py` (`_read` adds LIS-SKINS offers; `create_order(..., availability=None)` re-checks the choice)
- Modify: `apps/api/src/csmarket/modules/orders/routes.py:51-80` (the dependency)
- Modify: `infra/prometheus/alerts/api.yml:58-64` (comment: checkout now also asks LIS-SKINS `check-availability`, ADR-0012)
- Create: `apps/api/tests/integration/fake_lisskins_client.py` (`FakeAvailability`; Task 8 adds the buy client)
- Test: `apps/api/tests/integration/test_lisskins_availability.py`, `apps/api/tests/integration/test_orders_checkout_lisskins.py`

**Interfaces:**

- Consumes: `AvailabilityClient`, `Availability`, `availability_client`, `LisskinsError`, `LisskinsForbiddenError`, `LisskinsUnavailableError`, `to_units` (Task 2); `lisskins.offers_for` (Task 5); `merge_offers`, `parse_offer_id`, `Offer` (Task 5).
- Produces in `lisskins/availability.py`: `BUDGET_PER_MINUTE = 100`, `BREAKER_KEY = "lisskins:check:breaker"`, `BREAKER_TTL = 120`, `LiveCheck = Literal["available", "gone", "unknown"]`, `async live_price(redis, client: AvailabilityClient, skin_id: int) -> tuple[LiveCheck, int | None]`, `async recheck_chosen(offers: list[Offer], chosen: str, *, redis, client) -> list[Offer]`.
- Produces: `create_order(db, *, redis, user, body, idempotency_key, client, settings, availability: AvailabilityClient | None = None)`; `post_order` takes `availability: Annotated[AvailabilityClient, Depends(availability_client)]`.
- Produces (tests): `tests/integration/fake_lisskins_client.py::FakeAvailability(answer: Availability | Exception)` with `.calls: list[list[int]]`.

- [ ] **Step 1: Write the failing tests**

```python
# apps/api/tests/integration/fake_lisskins_client.py
"""Scripted LIS-SKINS clients for the orders tests."""

from __future__ import annotations

from collections.abc import Sequence

from csmarket.modules.lisskins.api import Availability


class FakeAvailability:
    """``check-availability``: the scripted :class:`Availability`, or the exception raised."""

    def __init__(self, answer: Availability | Exception) -> None:
        self.answer = answer
        self.calls: list[list[int]] = []

    async def check_availability(self, ids: Sequence[int]) -> Availability:
        """The scripted answer."""
        self.calls.append(list(ids))
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer
```

```python
# apps/api/tests/integration/test_lisskins_availability.py
"""The checkout's live look at a LIS-SKINS lot: budget, breaker, the three verdicts."""

from __future__ import annotations

from decimal import Decimal

import pytest
from csmarket.core.redis import get_redis
from csmarket.modules.lisskins import availability
from csmarket.modules.lisskins.api import (
    Availability,
    LisskinsError,
    LisskinsRateLimitedError,
    live_price,
    recheck_chosen,
)
from csmarket.modules.skins.api import Offer

from tests.integration.fake_lisskins_client import FakeAvailability

AVAILABLE = Availability(available={5: Decimal("9.00")}, unavailable=frozenset())


def _offer(offer_id: str, source: str, units: int) -> Offer:
    return Offer(
        offer_id=offer_id,
        source=source,  # type: ignore[arg-type]  # the test's literal
        price_units=units,
        float_value=None,
        paint_seed=None,
    )


async def test_the_three_verdicts() -> None:
    redis = get_redis()
    assert await live_price(redis, FakeAvailability(AVAILABLE), 5) == ("available", 9_000)
    gone = Availability(available={}, unavailable=frozenset({5}))
    assert await live_price(redis, FakeAvailability(gone), 5) == ("gone", None)
    neither = Availability(available={}, unavailable=frozenset())
    assert await live_price(redis, FakeAvailability(neither), 5) == ("unknown", None)


async def test_a_spent_budget_answers_unknown_without_a_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(availability, "BUDGET_PER_MINUTE", 1)
    fake = FakeAvailability(AVAILABLE)
    assert await live_price(get_redis(), fake, 5) == ("available", 9_000)
    assert await live_price(get_redis(), fake, 5) == ("unknown", None)
    assert len(fake.calls) == 1


async def test_an_outage_opens_the_breaker_and_a_refusal_does_not() -> None:
    redis = get_redis()
    refused = FakeAvailability(LisskinsError("bad", status=422, code="invalid_ids_value"))
    assert await live_price(redis, refused, 5) == ("unknown", None)
    assert not await redis.exists(availability.BREAKER_KEY)
    limited = FakeAvailability(LisskinsRateLimitedError("slow down", retry_after=3))
    assert await live_price(redis, limited, 5) == ("unknown", None)
    assert await redis.exists(availability.BREAKER_KEY)
    later = FakeAvailability(AVAILABLE)
    assert await live_price(redis, later, 5) == ("unknown", None)
    assert later.calls == []


async def test_recheck_touches_only_the_chosen_lisskins_offer() -> None:
    offers = [_offer("sl:1", "skinslink", 8_000), _offer("ls:5", "lisskins", 8_500)]
    fake = FakeAvailability(AVAILABLE)
    same = await recheck_chosen(offers, "sl:1", redis=get_redis(), client=fake)
    assert same == offers and fake.calls == []
    moved = await recheck_chosen(offers, "ls:5", redis=get_redis(), client=fake)
    assert [(o.offer_id, o.price_units) for o in moved] == [("sl:1", 8_000), ("ls:5", 9_000)]
    gone = FakeAvailability(Availability(available={}, unavailable=frozenset({5})))
    dropped = await recheck_chosen(offers, "ls:5", redis=get_redis(), client=gone)
    assert [o.offer_id for o in dropped] == ["sl:1"]
```

```python
# apps/api/tests/integration/test_orders_checkout_lisskins.py
"""``POST /orders`` for a LIS-SKINS lot (ADR-0012): one live check — the live price is
billed, a dearer one is ``price_changed``, a sold lot falls to the next offer, a failed call
accepts the snapshot price; another source's offer is never checked."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from csmarket.core import config as cfg
from csmarket.core.ids import new_id
from csmarket.core.redis import get_redis
from csmarket.modules.fx.api import record_snapshot
from csmarket.modules.lisskins.api import (
    Availability,
    LisskinsUnavailableError,
    availability_client,
)
from csmarket.modules.lisskins.availability import BREAKER_KEY
from csmarket.modules.lisskins.models import LisskinsOffer, LisskinsState
from csmarket.modules.orders.models import Order
from csmarket.modules.skins.api import search_client
from csmarket.modules.skins.models import SkinItem
from csmarket.modules.skinslink.models import SkinslinkItem, SkinslinkState
from fastapi import FastAPI
from httpx import AsyncClient, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.conftest import CUSTOMER_STEAM_ID, dev_login_headers
from tests.integration.fake_lisskins_client import FakeAvailability
from tests.integration.orders_factory import StubListings, saved_trade_link

pytestmark = pytest.mark.asyncio

SLUG = "ak-47-redline-ft"
ORDERS = "/api/v1/orders"
LOT = 5
Live = Callable[[Availability | Exception], FakeAvailability]


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for name, value in {
        "SKINS_BUY_ENABLED": "true",
        "WAXPEER_API_KEY": "k",
        "SKINSLINK_ENABLED": "true",
        "SKINSLINK_API_KEY": "k",
        "SKINSLINK_SECRET": "s",
        "LISSKINS_ENABLED": "true",
        "LISSKINS_API_KEY": "k",
    }.items():
        monkeypatch.setenv(f"CSMARKET_{name}", value)
    cfg.get_settings.cache_clear()
    yield
    cfg.get_settings.cache_clear()


@pytest.fixture
async def item(db_session: AsyncSession) -> SkinItem:
    await record_snapshot(db_session, rate=Decimal("12700"), source="cbu")
    row = SkinItem(
        id=new_id(),
        market_hash_name="AK-47 | Redline (Field-Tested)",
        phase="",
        slug=SLUG,
        category="rifles",
        weapon="AK-47",
        search_text=SLUG,
        active=True,
        cheapest_auto=[],
    )
    at = datetime.now(UTC)
    db_session.add_all(
        [
            row,
            SkinslinkState(id=1, cursor="c", mirror_synced_at=at),
            LisskinsState(id=1, snapshot_at=at, lots=1),
            LisskinsOffer(id=LOT, skin_item_id=row.id, price_units=9_000, asset_id="9"),
            SkinslinkItem(
                id="380",
                market_hash_name=row.market_hash_name,
                phase="",
                price_units=9_100,
                skin_item_id=row.id,
            ),
        ]
    )
    await db_session.commit()
    return row


@pytest.fixture
async def stub(integration_app: FastAPI, item: SkinItem) -> AsyncIterator[StubListings]:
    stub = StubListings()
    stub.register(item)
    await stub.set(SLUG, [])
    integration_app.dependency_overrides[search_client] = lambda: stub
    yield stub
    integration_app.dependency_overrides.pop(search_client, None)


@pytest.fixture
def live(integration_app: FastAPI) -> Iterator[Live]:
    def use(answer: Availability | Exception) -> FakeAvailability:
        fake = FakeAvailability(answer)
        integration_app.dependency_overrides[availability_client] = lambda: fake
        return fake

    yield use
    integration_app.dependency_overrides.pop(availability_client, None)


@pytest.fixture
async def headers(integration_client: AsyncClient, db_session: AsyncSession) -> dict[str, str]:
    h = await dev_login_headers(integration_client, steam_id=CUSTOMER_STEAM_ID, admin=False)
    await saved_trade_link(db_session, CUSTOMER_STEAM_ID)
    return h


async def _shown(api: AsyncClient, offer_id: str) -> int:
    r = await api.get(f"/api/v1/skins/{SLUG}/listings")
    assert r.status_code == 200, r.text
    return int(next(i for i in r.json()["items"] if i["listing_id"] == offer_id)["price_uzs"])


async def _post(api: AsyncClient, headers: dict[str, str], offer_id: str, price_uzs: int) -> Response:
    return await api.post(
        ORDERS,
        headers={**headers, "Idempotency-Key": f"order-{uuid.uuid4()}"},
        json={"slug": SLUG, "listing_id": offer_id, "price_uzs": price_uzs},
    )


async def _order(db: AsyncSession, number: str) -> Order:
    db.expire_all()
    order = await db.scalar(select(Order).where(Order.number == number))
    assert order is not None
    return order


def _available(usd: str) -> Availability:
    return Availability(available={LOT: Decimal(usd)}, unavailable=frozenset())


async def test_an_available_lot_is_billed_at_its_live_price(
    integration_client: AsyncClient,
    headers: dict[str, str],
    stub: StubListings,
    live: Live,
    db_session: AsyncSession,
) -> None:
    fake = live(_available("9.00"))
    shown = await _shown(integration_client, f"ls:{LOT}")
    r = await _post(integration_client, headers, f"ls:{LOT}", shown)
    assert r.status_code == 201, r.text
    order = await _order(db_session, r.json()["number"])
    assert (order.source, order.offer_id, order.listing_id, order.cost_units) == (
        "lisskins",
        "ls:5",
        None,
        9_000,
    )
    assert fake.calls == [[LOT]]


async def test_a_dearer_live_price_is_price_changed_never_the_snapshot_price(
    integration_client: AsyncClient, headers: dict[str, str], stub: StubListings, live: Live
) -> None:
    shown = await _shown(integration_client, f"ls:{LOT}")
    live(_available("9.90"))
    r = await _post(integration_client, headers, f"ls:{LOT}", shown)
    assert r.status_code == 409, r.text
    assert r.json()["code"] == "price_changed"
    assert int(r.json()["price_uzs"]) > shown


async def test_a_sold_lot_falls_to_the_next_offer(
    integration_client: AsyncClient,
    headers: dict[str, str],
    stub: StubListings,
    live: Live,
    db_session: AsyncSession,
) -> None:
    shown = await _shown(integration_client, f"ls:{LOT}")
    live(Availability(available={}, unavailable=frozenset({LOT})))
    r = await _post(integration_client, headers, f"ls:{LOT}", shown)
    assert r.status_code == 201, r.text
    order = await _order(db_session, r.json()["number"])
    assert (order.source, order.offer_id) == ("skinslink", "sl:380")
    assert order.price_uzs == shown  # within the ceiling: never more than the buyer saw


async def test_a_failed_check_accepts_the_snapshot_price_and_opens_the_breaker(
    integration_client: AsyncClient,
    headers: dict[str, str],
    stub: StubListings,
    live: Live,
    db_session: AsyncSession,
) -> None:
    fake = live(LisskinsUnavailableError("ReadTimeout"))
    shown = await _shown(integration_client, f"ls:{LOT}")
    first = await _post(integration_client, headers, f"ls:{LOT}", shown)
    second = await _post(integration_client, headers, f"ls:{LOT}", shown)
    assert (first.status_code, second.status_code) == (201, 201)
    assert (await _order(db_session, first.json()["number"])).cost_units == 9_000
    assert await get_redis().exists(BREAKER_KEY)
    assert fake.calls == [[LOT]]  # the breaker spared the second order a call


async def test_another_sources_offer_is_never_checked(
    integration_client: AsyncClient, headers: dict[str, str], stub: StubListings, live: Live
) -> None:
    fake = live(Availability(available={}, unavailable=frozenset({LOT})))
    r = await _post(integration_client, headers, "sl:380", await _shown(integration_client, "sl:380"))
    assert r.status_code == 201, r.text
    assert fake.calls == []
```

- [ ] **Step 2: Run them**

Run: `cd apps/api && uv run pytest tests/integration/test_lisskins_availability.py tests/integration/test_orders_checkout_lisskins.py -q`
Expected: FAIL — `ImportError: live_price`; checkout ignores `ls:` offers (`offer_gone`).

- [ ] **Step 3: Write `lisskins/availability.py`**

```python
"""Checkout's live look at one LIS-SKINS lot (spec 2026-10-07 §5, ADR-0012).

``POST /orders`` for an ``ls:`` offer asks ``GET /market/check-availability`` once — the
snapshot can be minutes old. Bounded like the item page's Waxpeer read (AGENTS §11): a 4 s
timeout (``lisskins_check_timeout_seconds``), :data:`BUDGET_PER_MINUTE` calls a minute for
the whole API, and a :data:`BREAKER_TTL` breaker after an outage. Gone → the offer is
dropped (checkout's substitute rule); no answer → the snapshot price stands (the worker's
``max_price`` is the money guard).
"""

from __future__ import annotations

import contextlib
from dataclasses import replace
from datetime import UTC, datetime
from typing import Literal

from redis.asyncio import Redis
from redis.exceptions import RedisError

from csmarket.core.logging import get_logger
from csmarket.modules.lisskins.client import (
    AvailabilityClient,
    LisskinsError,
    LisskinsForbiddenError,
    LisskinsUnavailableError,
)
from csmarket.modules.lisskins.export import to_units
from csmarket.modules.skins.api import Offer, merge_offers, parse_offer_id

log = get_logger("csmarket.lisskins.availability")

#: The key allows 200 requests a minute; half is left to the reconcile and the buys.
BUDGET_PER_MINUTE = 100
BREAKER_KEY = "lisskins:check:breaker"
BREAKER_TTL = 120
_BUDGET_TTL = 120

LiveCheck = Literal["available", "gone", "unknown"]


async def _budget_ok(redis: Redis) -> bool:
    """One more call this minute; a Redis outage does not stop checkout."""
    key = f"lisskins:check:budget:{datetime.now(UTC).strftime('%Y%m%d%H%M')}"
    with contextlib.suppress(RedisError):
        used = await redis.incr(key)
        await redis.expire(key, _BUDGET_TTL)
        return int(used) <= BUDGET_PER_MINUTE
    return True


async def _open_breaker(redis: Redis, error: Exception) -> None:
    log.warning("lisskins.check.breaker_open", error=type(error).__name__)
    with contextlib.suppress(RedisError):
        await redis.set(BREAKER_KEY, "1", ex=BREAKER_TTL)


async def live_price(
    redis: Redis, client: AvailabilityClient, skin_id: int
) -> tuple[LiveCheck, int | None]:
    """``("available", units)``, ``("gone", None)`` or ``("unknown", None)`` — the last when
    the breaker is open, the budget spent, or LIS-SKINS did not say."""
    breaker = False
    with contextlib.suppress(RedisError):
        breaker = bool(await redis.exists(BREAKER_KEY))
    if breaker or not await _budget_ok(redis):
        return "unknown", None
    try:
        answer = await client.check_availability([skin_id])
    except (LisskinsUnavailableError, LisskinsForbiddenError) as exc:  # 429 is "unavailable"
        await _open_breaker(redis, exc)
        return "unknown", None
    except LisskinsError as exc:
        log.warning("lisskins.check.refused", error=type(exc).__name__, code=exc.code)
        return "unknown", None
    price = answer.available.get(skin_id)
    if price is not None:
        return "available", to_units(price)
    if skin_id in answer.unavailable:
        return "gone", None
    return "unknown", None


async def recheck_chosen(
    offers: list[Offer], chosen: str, *, redis: Redis, client: AvailabilityClient
) -> list[Offer]:
    """``offers`` with the chosen LIS-SKINS lot at its live price, or without it when sold.

    No call (``offers`` unchanged) when the choice is another source's offer or not listed.
    """
    picked = next((o for o in offers if o.offer_id == chosen and o.source == "lisskins"), None)
    if picked is None:
        return offers
    verdict, units = await live_price(redis, client, int(parse_offer_id(chosen)[1]))
    log.info("lisskins.check", verdict=verdict)
    if verdict == "gone":
        return [o for o in offers if o is not picked]
    if verdict == "available" and units is not None and units != picked.price_units:
        return merge_offers([replace(o, price_units=units) if o is picked else o for o in offers])
    return offers


__all__ = ["BREAKER_KEY", "BREAKER_TTL", "BUDGET_PER_MINUTE", "LiveCheck", "live_price", "recheck_chosen"]
```

`lisskins/api.py` re-exports `live_price`, `recheck_chosen`, `offers_for`.

- [ ] **Step 4: Checkout and the route**

`orders/checkout.py`:

```python
from csmarket.modules.lisskins.api import AvailabilityClient, recheck_chosen
from csmarket.modules.lisskins.api import offers_for as lisskins_offers
from csmarket.modules.skinslink.api import offers_for as skinslink_offers
```

In `_ItemSnapshot.of`: `count_auto=item.stock_count,  # every source's stock, as the catalogue prices it`. In `_choose` the substitute's tie key becomes `key=lambda p: (p[1][1], TIE_ORDER[p[0].source], p[0].offer_id)` (import `TIE_ORDER` from `skins.api`; comment "Waxpeer, Skinslink, LIS-SKINS on a tie"). In `_read`:

```python
    at = now()
    extra = [
        *await skinslink_offers(db, item.id, settings=settings, now=at),
        *await lisskins_offers(db, item.id, settings=settings, now=at),
    ]
```

(`_Quoted.extra`'s comment: "Skinslink's and LIS-SKINS' offers, read inside the read transaction".) `create_order` gains the keyword `availability: AvailabilityClient | None = None` (docstring: "LIS-SKINS, for the chosen `ls:` lot's live price (ADR-0012); `None` checks nothing") and, right after `offers = merge_offers(...)`:

```python
    if availability is not None:  # one call, only for a chosen LIS-SKINS lot; no session held
        offers = await recheck_chosen(offers, body.listing_id, redis=redis, client=availability)
```

The module docstring's last paragraph adds: "A chosen LIS-SKINS lot is re-checked live (`lisskins.recheck_chosen`, one call, 4 s, budgeted, breaker-guarded): sold → the substitute rule; no answer → the snapshot price."

`orders/routes.py::post_order` — import `from csmarket.modules.lisskins.api import AvailabilityClient, availability_client`, add the parameter `availability: Annotated[AvailabilityClient, Depends(availability_client)],` after `client`, and pass `availability=availability` to `create_order` only while LIS-SKINS is on:

```python
    settings = get_settings()
    order, created = await create_order(
        db,
        redis=get_redis(),
        user=user,
        body=body,
        idempotency_key=key,
        client=client,
        settings=settings,
        availability=availability if settings.lisskins_active else None,
    )
```

`infra/prometheus/alerts/api.yml` — the comment block above `ApiHighLatency` adds: "checkout also asks LIS-SKINS `check-availability` for a chosen `ls:` lot (ADR-0012) — the route is already in the list."

- [ ] **Step 5: Run tests and gates**

Run: `cd apps/api && uv run pytest tests/integration/test_lisskins_availability.py tests/integration/test_orders_checkout_lisskins.py tests/integration/test_orders_checkout.py tests/integration/test_orders_checkout_sources.py -q && cd ../.. && make lint typecheck && make gen-api && docker run --rm -v "$PWD/infra/prometheus:/p:ro" --entrypoint promtool prom/prometheus:v3.12.0 check rules /p/alerts/api.yml`
Expected: PASS; clean; no OpenAPI drift (a dependency, no schema change); rules valid.

- [ ] **Step 6: Commit**

```bash
git add apps/api/src apps/api/tests infra/prometheus/alerts/api.yml
git commit -m "feat(api/orders): checkout re-checks a chosen LIS-SKINS lot live (one budgeted call, ADR-0012)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: One substitute rule for every buy path (`orders/substitutes.py`)

A refactor of the Skinslink path plus the pieces the LIS-SKINS path reuses. Every existing buying test stays green unchanged.

**Files:**

- Create: `apps/api/src/csmarket/modules/orders/substitutes.py`, `apps/api/src/csmarket/modules/orders/purchase_rows.py`
- Modify: `apps/api/src/csmarket/modules/orders/buy_lease.py:41-75` (`take_lease` finds the pending row by source in `PENDING_TABLES`)
- Modify: `apps/api/src/csmarket/modules/orders/buying.py:99-117,138` (`_pending_buy` → `substitutes.pending_buy`)
- Modify: `apps/api/src/csmarket/modules/orders/skinslink_buying.py:296-331` (`_substitute` → `substitutes.next_offer`; any other source → `skinslink_writes.switch`)
- Modify: `apps/api/src/csmarket/modules/orders/skinslink_writes.py:135-160` (`switch_to_waxpeer` → `switch`, via `substitutes.switch_source`)
- Test: `apps/api/tests/integration/test_orders_substitutes.py`; add one test to `apps/api/tests/integration/test_orders_skinslink_buying.py`

**Interfaces:**

- Consumes: `lisskins.offers_for` (Task 5), `skinslink.offers_for`, `LisskinsPurchase` (Task 3), `merge_offers` (Task 5).
- Produces in `orders/substitutes.py`:
  - `async stored_offers(db, skin_item_id: str, *, settings, now) -> list[Offer]` (Skinslink + LIS-SKINS, DB reads only)
  - `async next_offer(db, *, skin_item_id: str, ceiling: int, tried: set[str], settings, waxpeer: TradeClient | None) -> Offer | None` (ends the read transaction before any Waxpeer read; Waxpeer only while `waxpeer_buy_enabled`)
  - `pending_buy(order: Order, *, units: int, key: str) -> SkinTrade | SkinslinkPurchase | LisskinsPurchase`
  - `async switch_source(db, order: Order, offer: Offer) -> None` (the caller holds `order` locked and commits; the new row is keyed `<order id>:2` — Waxpeer's `project_id` stays the order id)
- Produces in `orders/purchase_rows.py`: `PurchaseRow = SkinslinkPurchase | LisskinsPurchase`; `PENDING_TABLES: dict[str, type[SkinTrade] | type[SkinslinkPurchase] | type[LisskinsPurchase]]`; `async purchase_of(db, order: Order, *, lock: bool) -> PurchaseRow | None` (read fresh; `None` for a Waxpeer order).
- Produces in `skinslink_writes.py`: `async switch(db, snap: PurchaseSnapshot, offer: Offer) -> str` (returns `lookup_later`; replaces `switch_to_waxpeer`).

- [ ] **Step 1: Write the failing tests**

```python
# apps/api/tests/integration/test_orders_substitutes.py
"""``orders.substitutes``: the cheapest other offer of any source within the ceiling, and
handing an order to another source's buy path."""

from __future__ import annotations

from csmarket.core import clock
from csmarket.core.config import get_settings
from csmarket.modules.lisskins.models import LisskinsOffer, LisskinsPurchase, LisskinsState
from csmarket.modules.orders.models import Order, SkinTrade
from csmarket.modules.orders.substitutes import next_offer, pending_buy, switch_source
from csmarket.modules.skins.api import Offer
from csmarket.modules.skins.models import SkinItem
from csmarket.modules.skinslink.models import SkinslinkItem, SkinslinkPurchase, SkinslinkState
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.fake_trade_client import FakeTradeClient
from tests.integration.orders_factory import make_item_and_rate, make_order

SETTINGS = get_settings().model_copy(
    update={
        "skinslink_enabled": True,
        "skinslink_api_key": "k",
        "skinslink_secret": "s",
        "lisskins_enabled": True,
        "lisskins_api_key": "k",
        "waxpeer_api_key": "test-key-not-real",
    }
)


async def _item(db: AsyncSession) -> SkinItem:
    item, _ = await make_item_and_rate(db)
    at = clock.now()
    db.add_all(
        [
            SkinslinkItem(id="100", market_hash_name=item.market_hash_name, phase="", price_units=12_345, skin_item_id=item.id),
            SkinslinkItem(id="101", market_hash_name=item.market_hash_name, phase="", price_units=12_500, skin_item_id=item.id),
            LisskinsOffer(id=5, skin_item_id=item.id, price_units=12_400, asset_id="9"),
        ]
    )
    await db.merge(SkinslinkState(id=1, cursor="c", mirror_synced_at=at))
    await db.merge(LisskinsState(id=1, snapshot_at=at, lots=1))
    await db.commit()
    return item


async def test_the_cheapest_other_offer_of_any_source_within_the_ceiling(
    db_session: AsyncSession,
) -> None:
    item = await _item(db_session)
    waxpeer = FakeTradeClient()
    waxpeer.listings(item.market_hash_name, [(777, 12_600)])
    kw = {"skin_item_id": item.id, "settings": SETTINGS, "waxpeer": waxpeer}
    first = await next_offer(db_session, ceiling=12_715, tried={"sl:100"}, **kw)  # type: ignore[arg-type]
    assert first is not None and first.offer_id == "ls:5"
    later = await next_offer(db_session, ceiling=12_715, tried={"sl:100", "ls:5", "sl:101"}, **kw)  # type: ignore[arg-type]
    assert later is not None and later.offer_id == "wx:777"
    assert await next_offer(db_session, ceiling=12_000, tried=set(), **kw) is None  # type: ignore[arg-type]


async def test_waxpeer_is_never_asked_while_its_buying_is_off(db_session: AsyncSession) -> None:
    item = await _item(db_session)
    waxpeer = FakeTradeClient()
    waxpeer.listings(item.market_hash_name, [(777, 12_600)])
    off = SETTINGS.model_copy(update={"waxpeer_buy_enabled": False})
    found = await next_offer(
        db_session,
        skin_item_id=item.id,
        ceiling=12_715,
        tried={"sl:100", "ls:5", "sl:101"},
        settings=off,
        waxpeer=waxpeer,
    )
    assert found is None and waxpeer.search_calls == 0


def test_pending_buy_is_keyed_by_source() -> None:
    ls = pending_buy(Order(id="o1", source="lisskins", offer_id="ls:5"), units=9_000, key="o1:2")
    assert isinstance(ls, LisskinsPurchase)
    assert (ls.custom_id, ls.skin_id, ls.paid_units, ls.buy_pending) == ("o1:2", 5, 9_000, True)
    sl = pending_buy(Order(id="o1", source="skinslink", offer_id="sl:380"), units=1, key="o1")
    assert isinstance(sl, SkinslinkPurchase) and (sl.merchant_tx_id, sl.asset_id) == ("o1", "380")
    wx = pending_buy(
        Order(id="o1", source="waxpeer", offer_id="wx:7", listing_id=7), units=1, key="o1:2"
    )
    assert isinstance(wx, SkinTrade) and (wx.project_id, wx.listing_id) == ("o1", 7)


async def test_switch_source_hands_a_skinslink_order_to_lisskins(db_session: AsyncSession) -> None:
    order = await make_order(
        db_session, status="buying", source="skinslink", offer_id="sl:100", listing_id=None
    )
    db_session.add(
        SkinslinkPurchase(
            order_id=order.id, merchant_tx_id=order.id, asset_id="100", paid_units=12_345, buy_pending=True
        )
    )
    await db_session.commit()
    locked = await db_session.scalar(select(Order).where(Order.id == order.id).with_for_update())
    assert locked is not None
    offer = Offer(offer_id="ls:5", source="lisskins", price_units=12_400, float_value=None, paint_seed=None)
    await switch_source(db_session, locked, offer)
    await db_session.commit()
    db_session.expire_all()
    p = await db_session.get(LisskinsPurchase, order.id)
    assert p is not None
    assert (p.custom_id, p.skin_id, p.paid_units, p.buy_pending) == (f"{order.id}:2", 5, 12_400, True)
    assert await db_session.get(SkinslinkPurchase, order.id) is None
    row = await db_session.get(Order, order.id)
    assert row is not None
    assert (row.source, row.offer_id, row.listing_id, row.next_check_at) == ("lisskins", "ls:5", None, None)
```

In `test_orders_skinslink_buying.py` add (imports `LisskinsOffer`, `LisskinsPurchase`, `LisskinsState` from `csmarket.modules.lisskins.models`):

```python
async def test_a_lisskins_substitute_hands_the_order_to_the_lisskins_path(
    db_session: AsyncSession, settings: Settings
) -> None:
    order = await _buying(db_session)
    db_session.add(LisskinsOffer(id=5, skin_item_id=order.skin_item_id, price_units=COST, asset_id="9"))
    await db_session.merge(LisskinsState(id=1, snapshot_at=clock.now(), lots=1))
    await db_session.commit()
    on = settings.model_copy(update={"lisskins_enabled": True, "lisskins_api_key": "k"})
    fake = FakeSkinslinkClient(purchase("failed", fail_reason="item_sold"))
    assert await attempt_skinslink_buy(db_session, fake, order_id=order.id, settings=on) == (
        "lookup_later"
    )
    row = await _order(db_session, order)
    assert (row.source, row.offer_id, row.status) == ("lisskins", "ls:5", "buying")
    p = await db_session.scalar(
        select(LisskinsPurchase)
        .where(LisskinsPurchase.order_id == order.id)
        .execution_options(populate_existing=True)
    )
    assert p is not None and (p.custom_id, p.paid_units, p.buy_pending) == (f"{order.id}:2", COST, True)
```

- [ ] **Step 2: Run them**

Run: `cd apps/api && uv run pytest tests/integration/test_orders_substitutes.py tests/integration/test_orders_skinslink_buying.py -q`
Expected: FAIL — `ModuleNotFoundError: csmarket.modules.orders.substitutes`; the Skinslink path never looks at LIS-SKINS.

- [ ] **Step 3: Write `orders/purchase_rows.py`**

```python
"""Which row holds an order's buy, by ``orders.source``."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.modules.lisskins.api import LisskinsPurchase
from csmarket.modules.orders.models import Order, SkinTrade
from csmarket.modules.skinslink.api import SkinslinkPurchase

#: A non-Waxpeer order's purchase row (the attention columns are the same on both).
PurchaseRow = SkinslinkPurchase | LisskinsPurchase
#: Where each source keeps its pending buy (``buy_lease.take_lease``).
PENDING_TABLES: dict[str, type[SkinTrade] | type[SkinslinkPurchase] | type[LisskinsPurchase]] = {
    "waxpeer": SkinTrade,
    "skinslink": SkinslinkPurchase,
    "lisskins": LisskinsPurchase,
}


async def purchase_of(db: AsyncSession, order: Order, *, lock: bool) -> PurchaseRow | None:
    """A Skinslink or LIS-SKINS order's purchase, read fresh (``FOR UPDATE`` with ``lock``,
    after the order — ruling K); ``None`` for a Waxpeer order."""
    if order.source == "skinslink":
        sl = select(SkinslinkPurchase).where(SkinslinkPurchase.order_id == order.id)
        sl = sl.with_for_update() if lock else sl
        return await db.scalar(sl.execution_options(populate_existing=True))
    if order.source == "lisskins":
        ls = select(LisskinsPurchase).where(LisskinsPurchase.order_id == order.id)
        ls = ls.with_for_update() if lock else ls
        return await db.scalar(ls.execution_options(populate_existing=True))
    return None


__all__ = ["PENDING_TABLES", "PurchaseRow", "purchase_of"]
```

(`LisskinsPurchase` must be re-exported by `lisskins/api.py` — done in Task 3.)

- [ ] **Step 4: Write `orders/substitutes.py`**

```python
"""One substitute rule for every buy path (specs 2026-10-06 §6, 2026-10-07 §5).

A refused offer is replaced at most once by the cheapest other offer of the item, of any
source, within the order's ceiling (``order_substitute_ceiling`` over the agreed cost).
:func:`next_offer` finds it — Skinslink's and LIS-SKINS' offers from our own tables, and
Waxpeer's listings through the item page's cached, budgeted read while Waxpeer buying is
on. :func:`switch_source` hands the order to another source's path: its pending buy is
keyed ``<order id>:2``, the key that tells that path the substitute was already taken.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.config import Settings
from csmarket.core.redis import get_redis
from csmarket.modules.lisskins.api import LisskinsPurchase
from csmarket.modules.lisskins.api import offers_for as lisskins_offers
from csmarket.modules.orders.buy_rules import TradeSearch
from csmarket.modules.orders.models import Order, SkinTrade
from csmarket.modules.skins.api import (
    Listing,
    Offer,
    SkinItem,
    TradeClient,
    from_listing,
    listings_budget,
    listings_for,
    merge_offers,
    parse_offer_id,
)
from csmarket.modules.skinslink.api import SkinslinkPurchase
from csmarket.modules.skinslink.api import offers_for as skinslink_offers


async def stored_offers(
    db: AsyncSession, skin_item_id: str, *, settings: Settings, now: datetime
) -> list[Offer]:
    """Skinslink's and LIS-SKINS' offers of the item (database reads only)."""
    return [
        *await skinslink_offers(db, skin_item_id, settings=settings, now=now),
        *await lisskins_offers(db, skin_item_id, settings=settings, now=now),
    ]


async def next_offer(
    db: AsyncSession,
    *,
    skin_item_id: str,
    ceiling: int,
    tried: set[str],
    settings: Settings,
    waxpeer: TradeClient | None,
) -> Offer | None:
    """The cheapest offer of the item not in ``tried``, at most ``ceiling`` units, any source.

    Ends the read transaction before the Waxpeer read (no lock across an external call).
    """
    item = await db.get(SkinItem, skin_item_id)
    if item is not None:
        db.expunge(item)  # read below with no transaction open
    extra = await stored_offers(db, skin_item_id, settings=settings, now=now())
    await db.commit()
    rows: list[Listing] = []
    if item is not None and waxpeer is not None and settings.waxpeer_buy_enabled:
        rows, _ = await listings_for(
            item,
            client=TradeSearch(waxpeer),
            redis=get_redis(),
            budget_per_minute=listings_budget(settings),
        )
    offers = merge_offers([from_listing(r) for r in rows], extra)
    return next(
        (o for o in offers if o.offer_id not in tried and 0 < o.price_units <= ceiling), None
    )


def pending_buy(
    order: Order, *, units: int, key: str
) -> SkinTrade | SkinslinkPurchase | LisskinsPurchase:
    """The row that holds ``order``'s pending buy at its source, keyed ``key`` (Skinslink's
    ``merchant_tx_id``, LIS-SKINS' ``custom_id``; Waxpeer's ``project_id`` is the order id,
    which its lookup searches by)."""
    _, raw = parse_offer_id(order.offer_id or "")
    if order.source == "skinslink":
        return SkinslinkPurchase(
            order_id=order.id, merchant_tx_id=key, asset_id=raw, paid_units=units, buy_pending=True
        )
    if order.source == "lisskins":
        return LisskinsPurchase(
            order_id=order.id, custom_id=key, skin_id=int(raw), paid_units=units, buy_pending=True
        )
    return SkinTrade(
        order_id=order.id,
        project_id=order.id,
        listing_id=order.listing_id,
        paid_units=units,
        buy_pending=True,
        seller={},
    )


async def switch_source(db: AsyncSession, order: Order, offer: Offer) -> None:
    """Hand the locked ``order`` to ``offer``'s (other) source: the refused purchase row goes,
    a pending one keyed ``<order id>:2`` takes its place, and the order is due at once. The
    caller commits."""
    for table in (SkinslinkPurchase, LisskinsPurchase):
        await db.execute(delete(table).where(table.order_id == order.id))
    order.source, order.offer_id, order.listing_id = offer.source, offer.offer_id, offer.listing_id
    db.add(pending_buy(order, units=offer.price_units, key=f"{order.id}:2"))
    order.next_check_at = None


__all__ = ["next_offer", "pending_buy", "stored_offers", "switch_source"]
```

- [ ] **Step 5: Use them**

`buy_lease.take_lease` — import `PENDING_TABLES` from `orders.purchase_rows`; the docstring's `source` line becomes "`source` names where the pending buy lives (`purchase_rows.PENDING_TABLES`)"; the body:

```python
    table = PENDING_TABLES.get(source, SkinTrade)
    pending = (
        select(table.order_id)
        .where(table.order_id == Order.id, table.buy_pending.is_(True))
        .exists()
    )
```

(drop the `SkinslinkPurchase` import there.)

`buying.py` — delete `_pending_buy`; in `_claim`: `db.add(pending_buy(order, units=order.cost_units, key=order.id))` (import from `orders.substitutes`).

`skinslink_writes.py` — replace `switch_to_waxpeer` with:

```python
async def switch(db: AsyncSession, snap: PurchaseSnapshot, offer: Offer) -> str:
    """A substitute of another source: the order becomes that source's order whose buy is
    pending (its path buys it next); the Skinslink purchase row goes."""
    pair = await _locked(db, snap)
    if pair is None or (offer.source == "waxpeer" and offer.listing_id is None):
        return _stale(snap, "lookup_later")
    await switch_source(db, pair[0], offer)
    await db.commit()
    log.info("orders.skinslink_buy.switched", number=snap.number, source=offer.source)
    return "lookup_later"
```

(import `switch_source` from `orders.substitutes`; drop the now-unused `SkinTrade`/`delete` imports; `__all__` swaps `switch_to_waxpeer` for `switch`.)

`skinslink_buying.py` — delete `_substitute` and its now-unused imports; in `_buy`:

```python
        nxt = await next_offer(
            db,
            skin_item_id=snap.skin_item_id,
            ceiling=ceiling,
            tried=tried,
            settings=settings,
            waxpeer=waxpeer,
        )
        if nxt is None:
            break
        if nxt.source != "skinslink":
            return await switch(db, snap, nxt)
```

and the module docstring's step 4 says "the cheapest other offer of the item, of any source (`orders.substitutes`) … a Skinslink one is bought under `<order id>:2`; another source's turns the order into that source's order for its path".

- [ ] **Step 6: Run tests and gates**

Run: `cd apps/api && uv run pytest tests/integration/test_orders_substitutes.py tests/integration/test_orders_skinslink_buying.py tests/integration/test_orders_buying.py tests/integration/test_orders_buying_drain.py tests/integration/test_orders_buying_races.py tests/integration/test_orders_trade_identity.py tests/integration/test_skinslink_status.py -q && cd ../.. && make lint typecheck`
Expected: PASS (every existing suite unchanged); clean.

- [ ] **Step 7: Commit**

```bash
git add apps/api/src apps/api/tests
git commit -m "refactor(api/orders): one substitute rule across sources; a buy can be handed to any other source" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: LIS-SKINS statuses on orders; the buyer's card; attentions and health across sources

Decisions: a `return` whose reason starts with `rollback_` (LIS-SKINS has two: the buyer's and the seller's — the second is spelled with the banned word, so the prefix is matched) opens `rolled_back` whatever the order's status, never refunds; a `trade_create_error` whose `error` is not a trade-link code refunds `sold_out` (nothing reached the buyer); the dashboard's «Требуют внимания» counted Waxpeer trades only — it now counts every source's open attentions (one query, three sub-selects).

**Files:**

- Create: `apps/api/src/csmarket/modules/orders/lisskins_status.py`
- Modify: `apps/api/src/csmarket/modules/orders/refunds.py` (`refund_or_hold`; `_refuse_while_unresolved` reads the purchase through `purchase_rows.purchase_of`)
- Modify: `apps/api/src/csmarket/modules/orders/skinslink_status.py` (its `_refund` → `refunds.refund_or_hold`)
- Modify: `apps/api/src/csmarket/modules/orders/trade_view.py` (the LIS-SKINS card)
- Modify: `apps/api/src/csmarket/modules/orders/service.py:25-110` (rows join `lisskins_purchases`)
- Modify: `apps/api/src/csmarket/modules/orders/admin_actions.py:310-345` (`resolve_attention` via `purchase_of`)
- Modify: `apps/api/src/csmarket/modules/orders/health.py` (three sources; `open_attentions` public)
- Modify: `apps/api/src/csmarket/modules/orders/dashboard.py:139-150` (`_now_counts` counts every source)
- Modify: `apps/api/src/csmarket/modules/orders/api.py` (export `apply_lisskins_report`)
- Create: `apps/api/tests/integration/lisskins_factory.py`; extend `apps/api/tests/integration/fake_lisskins_client.py`
- Test: `apps/api/tests/integration/test_lisskins_status.py`; add to `test_orders_health.py`, `test_admin_orders_actions.py`, `test_admin_dashboard.py`

**Interfaces:**

- Consumes: `Purchase`, `PurchasedSkin`, `TRADE_LINK_ERRORS`, `to_units` (Task 2); `LisskinsPurchase` (Task 3); `purchase_of`, `PurchaseRow` (Task 7).
- Produces in `orders/lisskins_status.py`: `mirror_report(purchase: LisskinsPurchase, report: Purchase) -> PurchasedSkin`; `async apply_report(db, *, order: Order, purchase: LisskinsPurchase, report: Purchase) -> str` — outcomes `unchanged`, `trade_sent`, `delivered`, `returned`, `failed`, `rolled_back`, `ambiguous`, `held`; never commits; `async lock(db, order_id) -> tuple[Order, LisskinsPurchase] | None` (order, then purchase, `FOR UPDATE`, read fresh; the reconcile uses it).
- Produces in `orders/refunds.py`: `async refund_or_hold(db, order: Order, to: RefundStatus, reason: str) -> str` (`to`, or `held` while an open attention blocks the refund).
- Produces in `orders/trade_view.py`: `lisskins_state(order, purchase: LisskinsPurchase | None) -> SkinTradeState`; `skin_trade_out(order, trade, *, purchase: SkinslinkPurchase | LisskinsPurchase | None = None)`.
- Produces in `orders/health.py`: `async open_attentions(db) -> int`.
- Produces (tests): `lisskins_factory.make_lisskins_order(db, *, status="trade_sent", skin_status="wait_accept", order: dict[str, object] | None = None, **purchase) -> tuple[Order, LisskinsPurchase]`, `PRICE`, `OFFER`; `fake_lisskins_client.skin(status, **over) -> PurchasedSkin`, `purchase(status="processing", *, custom_id="o", purchase_id=55, **skin_over) -> Purchase`, `FakeLisskinsClient(*script, infos: dict[str, Purchase] | None = None, info_error: Exception | None = None)` with `.calls`, `.info_calls`.

- [ ] **Step 1: Test helpers**

```python
# apps/api/tests/integration/lisskins_factory.py
"""LIS-SKINS orders for the status, reconcile and admin tests."""

from __future__ import annotations

from decimal import Decimal

from csmarket.core import clock
from csmarket.modules.lisskins.models import LisskinsPurchase
from csmarket.modules.orders.models import Order
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.orders_factory import make_order

PRICE = Decimal(171_800)
#: A made-up Steam trade offer id.
OFFER = "7252638866"


async def make_lisskins_order(
    db: AsyncSession,
    *,
    status: str = "trade_sent",
    skin_status: str | None = "wait_accept",
    order: dict[str, object] | None = None,
    **purchase: object,
) -> tuple[Order, LisskinsPurchase]:
    """A kassa-paid LIS-SKINS order in ``status`` and its purchase with ``skin_status``
    (``order`` / ``purchase`` override any column)."""
    row = await make_order(
        db,
        status=status,
        paid_with="payme",
        paid_at=clock.now(),
        price_uzs=PRICE,
        source="lisskins",
        offer_id="ls:125345",
        listing_id=None,
        cost_units=12_340,
        **(order or {}),
    )
    values: dict[str, object] = {
        "order_id": row.id,
        "custom_id": row.id,
        "skin_id": 125345,
        "paid_units": 12_340,
        "purchase_id": 55,
        "status": skin_status,
        "steam_trade_offer_id": OFFER if skin_status == "wait_accept" else None,
        "buy_pending": False,
    }
    values.update(purchase)
    p = LisskinsPurchase(**values)
    db.add(p)
    await db.commit()
    return row, p
```

Extend `fake_lisskins_client.py` (merge these imports into the file's import block at the top):

```python
from collections import deque
from decimal import Decimal

from csmarket.modules.lisskins.api import Purchase, PurchasedSkin


def skin(status: str = "processing", **over: object) -> PurchasedSkin:
    """A LIS-SKINS skin report (``over`` replaces any field)."""
    base: dict[str, object] = {
        "id": 125345,
        "price_usd": Decimal("12.34"),
        "status": status,
        "return_reason": None,
        "error": None,
        "offer_id": None,
        "offer_expiry_at": None,
    }
    base.update(over)
    return PurchasedSkin(**base)  # type: ignore[arg-type]  # the test's own field values


def purchase(
    status: str = "processing", *, custom_id: str = "o", purchase_id: int = 55, **skin_over: object
) -> Purchase:
    """A purchase of one skin in ``status``."""
    return Purchase(purchase_id=purchase_id, custom_id=custom_id, skins=(skin(status, **skin_over),))


class FakeLisskinsClient:
    """``script``: ``buy`` answers (a :class:`Purchase`) or exceptions, popped per call;
    ``infos``: ``info`` answers by ``custom_id``; ``info_error``: raised by ``info``."""

    def __init__(
        self,
        *script: object,
        infos: dict[str, Purchase] | None = None,
        info_error: Exception | None = None,
    ) -> None:
        self.script = deque(script)
        self.infos = infos if infos is not None else {}
        self.info_error = info_error
        self.calls: list[dict[str, object]] = []
        self.info_calls: list[list[str]] = []

    async def buy(
        self, *, skin_id: int, partner: int, token: str, max_price_usd: Decimal, custom_id: str
    ) -> Purchase:
        """The next scripted answer."""
        self.calls.append({"skin_id": skin_id, "custom_id": custom_id, "max_price_usd": max_price_usd})
        nxt = self.script.popleft()
        if isinstance(nxt, BaseException):
            raise nxt
        assert isinstance(nxt, Purchase)
        return nxt

    async def info(self, *, custom_ids: Sequence[str]) -> list[Purchase]:
        """The configured purchases among ``custom_ids``."""
        self.info_calls.append(list(custom_ids))
        if self.info_error is not None:
            raise self.info_error
        return [self.infos[c] for c in custom_ids if c in self.infos]
```

- [ ] **Step 2: Write the failing tests**

```python
# apps/api/tests/integration/test_lisskins_status.py
"""``orders.lisskins_status.apply_report``: spec 2026-10-07 §6 row by row, and the buyer's
card for a LIS-SKINS order."""

from __future__ import annotations

from decimal import Decimal

import pytest
from csmarket.modules.lisskins.api import Purchase
from csmarket.modules.lisskins.models import LisskinsPurchase
from csmarket.modules.orders.lisskins_status import apply_report
from csmarket.modules.orders.models import Order
from csmarket.modules.orders.trade_view import skin_trade_out
from csmarket.modules.wallet.api import user_balance
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.fake_lisskins_client import purchase
from tests.integration.lisskins_factory import OFFER, PRICE, make_lisskins_order

EXPIRY = "2026-10-07T19:50:35.000000Z"


async def _apply(db: AsyncSession, order: Order, report: Purchase) -> tuple[str, Order, LisskinsPurchase]:
    locked = await db.scalar(
        select(Order).where(Order.id == order.id).with_for_update().execution_options(populate_existing=True)
    )
    p = await db.scalar(
        select(LisskinsPurchase)
        .where(LisskinsPurchase.order_id == order.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert locked is not None and p is not None
    outcome = await apply_report(db, order=locked, purchase=p, report=report)
    await db.commit()
    return outcome, locked, p


async def test_processing_changes_nothing(db_session: AsyncSession) -> None:
    order, _ = await make_lisskins_order(db_session, status="buying", skin_status=None)
    outcome, row, p = await _apply(db_session, order, purchase("processing", custom_id=order.id))
    assert (outcome, row.status, p.status, p.amount_units) == ("unchanged", "buying", "processing", 12_340)


async def test_wait_accept_sends_the_trade_with_its_deadline(db_session: AsyncSession) -> None:
    order, _ = await make_lisskins_order(db_session, status="buying", skin_status=None)
    report = purchase("wait_accept", custom_id=order.id, offer_id=OFFER, offer_expiry_at=EXPIRY)
    outcome, row, p = await _apply(db_session, order, report)
    assert (outcome, row.status, p.steam_trade_offer_id) == ("trade_sent", "trade_sent", OFFER)
    card = skin_trade_out(row, None, purchase=p)
    assert card is not None and card.state == "offer_sent"
    assert card.offer_url == f"https://steamcommunity.com/tradeoffer/{OFFER}/"
    assert card.send_until is not None and card.send_until.isoformat().startswith("2026-10-07T19:50:35")


async def test_accepted_delivers(db_session: AsyncSession) -> None:
    order, _ = await make_lisskins_order(db_session)
    outcome, row, p = await _apply(db_session, order, purchase("accepted", custom_id=order.id))
    assert (outcome, row.status) == ("delivered", "delivered")
    card = skin_trade_out(row, None, purchase=p)
    assert card is not None and card.state == "accepted"


@pytest.mark.parametrize("reason", ["trade_timeout", "trade_canceled", "manual_cancel"])
async def test_a_trade_not_accepted_is_returned_and_refunded(
    db_session: AsyncSession, reason: str
) -> None:
    order, _ = await make_lisskins_order(db_session)
    report = purchase("return", custom_id=order.id, return_reason=reason)
    outcome, row, p = await _apply(db_session, order, report)
    assert (outcome, row.status, row.failure_reason) == ("returned", "returned", "not_accepted")
    assert await user_balance(db_session, order.user_id) == PRICE
    card = skin_trade_out(row, None, purchase=p)
    assert card is not None and (card.state, card.reason_code) == ("failed", "not_accepted")


@pytest.mark.parametrize(
    ("error", "reason"),
    [("private_inventory", "invalid_trade_link"), ("user_inventory_full", "invalid_trade_link"), ("unknown_error", "sold_out"), (None, "sold_out")],
)
async def test_a_trade_that_could_not_be_created_fails_and_refunds(
    db_session: AsyncSession, error: str | None, reason: str
) -> None:
    order, _ = await make_lisskins_order(db_session, status="buying", skin_status="processing")
    report = purchase("return", custom_id=order.id, return_reason="trade_create_error", error=error)
    outcome, row, _ = await _apply(db_session, order, report)
    assert (outcome, row.status, row.failure_reason) == ("failed", "failed", reason)
    assert await user_balance(db_session, order.user_id) == PRICE


@pytest.mark.parametrize("reason", ["rollback_user", "rollback_" + "supplier"])
async def test_a_rollback_is_an_attention_never_a_refund(db_session: AsyncSession, reason: str) -> None:
    order, _ = await make_lisskins_order(db_session, status="delivered", skin_status="accepted")
    report = purchase("return", custom_id=order.id, return_reason=reason)
    outcome, row, p = await _apply(db_session, order, report)
    assert (outcome, row.status, p.attention_reason) == ("rolled_back", "delivered", "rolled_back")
    assert await user_balance(db_session, order.user_id) == Decimal(0)
    card = skin_trade_out(row, None, purchase=p)
    assert card is not None and card.reason_code == "support"
    assert (await _apply(db_session, order, report))[0] == "unchanged"  # already open


@pytest.mark.parametrize("status", ["wait_unlock", "wait_withdraw"])
async def test_a_locked_lot_is_ambiguous(db_session: AsyncSession, status: str) -> None:
    order, _ = await make_lisskins_order(db_session, status="buying", skin_status=None)
    outcome, row, p = await _apply(db_session, order, purchase(status, custom_id=order.id))
    assert (outcome, row.status, p.attention_reason) == ("ambiguous", "buying", "ambiguous_trade")


async def test_a_refund_an_attention_blocks_is_held(db_session: AsyncSession) -> None:
    order, _ = await make_lisskins_order(db_session, attention_reason="buy_unconfirmed")
    report = purchase("return", custom_id=order.id, return_reason="trade_timeout")
    outcome, row, _ = await _apply(db_session, order, report)
    assert (outcome, row.status) == ("held", "trade_sent")
```

In `test_orders_health.py` add (import `make_lisskins_order`):

```python
async def test_lisskins_orders_count_like_any_other(db: AsyncSession) -> None:
    claimed = core_clock.now() - timedelta(minutes=31)
    await make_lisskins_order(
        db, status="buying", skin_status=None, order={"claimed_at": claimed}, attention_reason="source_forbidden"
    )
    await make_lisskins_order(db, status="buying", skin_status=None, order={"claimed_at": claimed})
    await make_lisskins_order(db, last_polled_at=core_clock.now() - timedelta(minutes=31))
    health = await _measure(db)
    assert (health.buying_stuck, health.trade_sent_unpolled, health.attention) == (1, 1, 1)
```

In `test_admin_orders_actions.py` add (import `make_lisskins_order`, `LisskinsPurchase`):

```python
async def test_resolve_works_on_a_lisskins_purchase(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    h = await admin_headers()
    order, _ = await make_lisskins_order(db_session, attention_reason="rolled_back")
    status, body = await _post(integration_client, h, order, "resolve", body={"note": "checked"})
    assert status == 200, body
    db_session.expire_all()
    p = await db_session.get(LisskinsPurchase, order.id)
    assert p is not None and p.resolved_at is not None and p.resolved_note == "checked"
    (row,) = await _audit(db_session, "orders.trade.resolve")
    assert row.payload == {"reason": "rolled_back"}
```

In `test_admin_dashboard.py` add (imports `make_skinslink_order`, `make_lisskins_order`):

```python
async def test_attention_counts_every_source(
    integration_client: AsyncClient, db_session: AsyncSession, headers: dict[str, str]
) -> None:
    order = await make_order(db_session, status="trade_sent", paid_with="payme", paid_at=NOW)
    await make_trade(db_session, order, attention_reason="ambiguous_trade")
    await make_skinslink_order(db_session, attention_reason="rolled_back")
    await make_lisskins_order(db_session, attention_reason="buy_unconfirmed")
    body = await _get(integration_client, headers, 1)
    assert body["attention"] == 3
```

- [ ] **Step 3: Run them**

Run: `cd apps/api && uv run pytest tests/integration/test_lisskins_status.py tests/integration/test_orders_health.py tests/integration/test_admin_orders_actions.py tests/integration/test_admin_dashboard.py -q`
Expected: FAIL — `ModuleNotFoundError: csmarket.modules.orders.lisskins_status`; health, resolve and the dashboard ignore LIS-SKINS.

- [ ] **Step 4: Write `orders/lisskins_status.py`**

```python
"""A LIS-SKINS purchase's status applied to its order (spec 2026-10-07 §6).

:func:`apply_report` mirrors LIS-SKINS' report onto ``lisskins_purchases`` and moves the
order as the skin's status says. Callers hold the order row, then the purchase row,
``FOR UPDATE`` (ruling K) and commit. The buy (``lisskins_writes``) and the reconcile
(``lisskins_reconcile``) call it; there is no webhook.

==========================================  ==================================================
``processing``                              nothing
``wait_accept`` with an offer               ``buying → trade_sent`` (+ the letter with the
                                            offer's expiry, a nudge)
``accepted``                                ``→ delivered``
``return``, ``rollback_…`` / after delivery attention ``rolled_back`` (the skin may be spent)
``return``, ``trade_create_error``, before  ``failed`` + refund ``invalid_trade_link`` (a link
an offer                                    error) or ``sold_out``
``return``, any other reason                ``returned`` + refund ``not_accepted``
``wait_unlock`` / ``wait_withdraw``         attention ``ambiguous_trade`` (we never buy
                                            locked lots)
==========================================  ==================================================

A refund an open attention blocks (R3) leaves the order as it is (``held``).
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.logging import get_logger
from csmarket.modules.lisskins.api import (
    TRADE_LINK_ERRORS,
    LisskinsPurchase,
    Purchase,
    PurchasedSkin,
    to_units,
)
from csmarket.modules.orders.fsm import TRANSITIONS, move
from csmarket.modules.orders.letters import enqueue_trade_sent
from csmarket.modules.orders.models import Order
from csmarket.modules.orders.refunds import refund_or_hold
from csmarket.modules.orders.trades import flag
from csmarket.modules.realtime.api import nudge

log = get_logger("csmarket.orders.lisskins_status")

#: Outcomes that change what the buyer sees; a refund is nudged by the refund itself.
_NUDGED = frozenset({"trade_sent", "delivered", "rolled_back", "ambiguous"})


def _when(text: str | None) -> datetime | None:
    """An ISO 8601 time from LIS-SKINS, UTC; ``None`` when absent or unreadable."""
    if not text:
        return None
    try:
        at = datetime.fromisoformat(text)
    except ValueError:
        return None
    return at if at.tzinfo is not None else at.replace(tzinfo=UTC)


def mirror_report(purchase: LisskinsPurchase, report: Purchase) -> PurchasedSkin:
    """Copy what LIS-SKINS reports onto ``purchase`` (a missing field never erases ours);
    returns the skin the order bought."""
    skin = next((s for s in report.skins if s.id == purchase.skin_id), report.skin)
    purchase.purchase_id = report.purchase_id
    purchase.status = skin.status
    purchase.return_reason = skin.return_reason or purchase.return_reason
    purchase.error = skin.error or purchase.error
    purchase.steam_trade_offer_id = skin.offer_id or purchase.steam_trade_offer_id
    purchase.offer_expiry_at = _when(skin.offer_expiry_at) or purchase.offer_expiry_at
    if skin.price_usd is not None:
        purchase.amount_units = to_units(skin.price_usd)
    purchase.last_polled_at = purchase.updated_at = now()
    return skin


async def _returned(
    db: AsyncSession, *, order: Order, purchase: LisskinsPurchase, skin: PurchasedSkin
) -> str:
    reason = skin.return_reason or ""
    # Both rollback reasons (the buyer's and the seller's) undo an accepted trade: the skin
    # may have been used — an admin decides, never an automatic refund.
    if reason.startswith("rollback_") or order.status == "delivered":
        if flag(purchase, "rolled_back"):
            log.error("orders.lisskins.rolled_back", number=order.number)
            return "rolled_back"
        return "unchanged"
    if order.status not in ("buying", "trade_sent"):
        return "unchanged"
    if reason == "trade_create_error" and order.status == "buying":
        why = "invalid_trade_link" if skin.error in TRADE_LINK_ERRORS else "sold_out"
        return await refund_or_hold(db, order, "failed", why)
    return await refund_or_hold(db, order, "returned", "not_accepted")


async def _apply(
    db: AsyncSession, *, order: Order, purchase: LisskinsPurchase, skin: PurchasedSkin
) -> str:
    if skin.status == "wait_accept":
        if skin.offer_id and order.status == "buying":
            move(order, "trade_sent")
            return "trade_sent"
        return "unchanged"
    if skin.status == "accepted":
        if "delivered" not in TRANSITIONS.get(order.status, frozenset()):
            return "unchanged"
        move(order, "delivered")
        return "delivered"
    if skin.status in ("wait_unlock", "wait_withdraw"):
        return "ambiguous" if flag(purchase, "ambiguous_trade") else "unchanged"
    if skin.status == "return":
        return await _returned(db, order=order, purchase=purchase, skin=skin)
    return "unchanged"  # processing, or a word LIS-SKINS adds later


async def apply_report(
    db: AsyncSession, *, order: Order, purchase: LisskinsPurchase, report: Purchase
) -> str:
    """Mirror ``report`` onto ``purchase`` and move ``order`` as the table above says.

    Args:
        db: Session; the caller holds ``order``, then ``purchase``, ``FOR UPDATE`` and
            commits. Never commits.
        order: The order, locked.
        purchase: Its purchase, locked.
        report: LIS-SKINS' report of the purchase.

    Returns:
        ``unchanged``, ``trade_sent``, ``delivered``, ``returned``, ``failed``,
        ``rolled_back``, ``ambiguous`` or ``held``.
    """
    skin = mirror_report(purchase, report)
    outcome = await _apply(db, order=order, purchase=purchase, skin=skin)
    if outcome in _NUDGED:
        await nudge(db, user_id=order.user_id, number=order.number)
    if outcome == "trade_sent":
        await enqueue_trade_sent(db, order, send_until=purchase.offer_expiry_at)
    return outcome


async def lock(db: AsyncSession, order_id: str) -> tuple[Order, LisskinsPurchase] | None:
    """The order, then its purchase, ``FOR UPDATE`` (ruling K), read fresh."""
    order = await db.scalar(
        select(Order).where(Order.id == order_id).with_for_update().execution_options(populate_existing=True)
    )
    purchase = await db.scalar(
        select(LisskinsPurchase)
        .where(LisskinsPurchase.order_id == order_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return None if order is None or purchase is None else (order, purchase)


__all__ = ["apply_report", "lock", "mirror_report"]
```

`orders/api.py` exports `apply_report` from it as `apply_lisskins_report`.

- [ ] **Step 5: Refunds, the Skinslink status, the card, the reads, «Разобрано», health, dashboard**

`refunds.py` — add, after `refund_to_balance`:

```python
async def refund_or_hold(db: AsyncSession, order: Order, to: RefundStatus, reason: str) -> str:
    """Refund ``order`` (actor ``orders``); ``held`` while an open attention blocks it (R3).

    Returns:
        ``to``, or ``held``.
    """
    try:
        await refund_to_balance(db, order=order, to_status=to, reason=reason, actor="orders")
    except ConflictError as exc:
        if exc.extra.get("code") != "order_needs_attention":
            raise
        return "held"
    return to
```

and `_refuse_while_unresolved` becomes:

```python
async def _refuse_while_unresolved(db: AsyncSession, order: Order) -> None:
    """409 ``order_needs_attention`` while the trade's outcome is unknown or spent (R3)."""
    # A Skinslink or LIS-SKINS order keeps its attention on its purchase row.
    trade: SkinTrade | PurchaseRow | None = await _trade_of(db, order) or await purchase_of(
        db, order, lock=False
    )
    if trade is not None and trade.attention_reason in BLOCKS_REFUND and trade.resolved_at is None:
        raise ConflictError("this order waits for an admin's check", code="order_needs_attention")
```

(import `PurchaseRow`, `purchase_of` from `orders.purchase_rows`; drop the `SkinslinkPurchase` import.) In `skinslink_status.py` delete `_refund` and call `refund_or_hold(db, order, "returned", "not_accepted")` / `refund_or_hold(db, order, "failed", _failure_reason(report.fail_reason))`.

`trade_view.py` — module docstring adds: "A LIS-SKINS order (spec 2026-10-07 §6) reads its purchase too: `processing` → `buying`, `wait_accept` → `offer_sent` (its expiry as `send_until`), `accepted` or a delivered order → `accepted`, `return` → `failed`." Then:

```python
_LISSKINS_STATES: dict[str, SkinTradeState] = {
    "wait_accept": "offer_sent",
    "accepted": "accepted",
    "return": "failed",
}


def lisskins_state(order: Order, purchase: LisskinsPurchase | None) -> SkinTradeState:
    """A LIS-SKINS order's trade state as the buyer reads it."""
    if order.status in ("failed", "returned"):
        return "failed"
    if order.status == "delivered":
        return "accepted"  # a later rollback shows as ``support``, never as a failure
    status = None if purchase is None else purchase.status
    return _LISSKINS_STATES.get(status or "", "buying")


def _lisskins_out(order: Order, purchase: LisskinsPurchase) -> SkinTradeOut:
    """A LIS-SKINS order's trade card."""
    state = lisskins_state(order, purchase)
    reason: SkinTradeReason | None = None
    if state == "failed":
        reason = _reason(order, purchase)
    elif _needs_support(purchase):
        reason = "support"
    offer = purchase.steam_trade_offer_id
    return SkinTradeOut(
        state=state,
        reason_code=reason,
        offer_url=f"https://steamcommunity.com/tradeoffer/{offer}/" if offer else None,
        send_until=purchase.offer_expiry_at if state == "offer_sent" else None,
        refunded_to="balance" if order.refunded_to == "balance" else None,
    )
```

`_needs_support` / `_reason` take `SkinTrade | SkinslinkPurchase | LisskinsPurchase | None`; `skin_trade_out`'s `purchase` parameter becomes `SkinslinkPurchase | LisskinsPurchase | None` and its body starts:

```python
    if isinstance(purchase, LisskinsPurchase):
        return _lisskins_out(order, purchase)
    if purchase is not None:
        return _purchase_out(order, purchase)
```

(`from csmarket.modules.lisskins.api import LisskinsPurchase`; `__all__` adds `lisskins_state`.)

`service.py` — `OrderRow.purchase: SkinslinkPurchase | LisskinsPurchase | None`; `order_out(..., purchase: SkinslinkPurchase | LisskinsPurchase | None = None)`; `_rows()` selects and outer-joins `LisskinsPurchase` too:

```python
def _rows() -> Select[Order, SkinTrade, str | None, SkinslinkPurchase, LisskinsPurchase]:
    # Outer joins: each of the three is ``None`` on a row without one.
    return (
        select(Order, SkinTrade, SkinItem.image_url, SkinslinkPurchase, LisskinsPurchase)
        .join(SkinItem, SkinItem.id == Order.skin_item_id)
        .outerjoin(SkinTrade, SkinTrade.order_id == Order.id)
        .outerjoin(SkinslinkPurchase, SkinslinkPurchase.order_id == Order.id)
        .outerjoin(LisskinsPurchase, LisskinsPurchase.order_id == Order.id)
    )


def _row(
    order: Order,
    trade: SkinTrade | None,
    image: str | None,
    sl: SkinslinkPurchase | None,
    ls: LisskinsPurchase | None,
) -> OrderRow:
    return OrderRow(
        order=order,
        trade=trade,
        image_url=steam_image(image, host=get_settings().skins_image_host),
        purchase=sl or ls,
    )
```

and `get_owned` unpacks `order, trade, image, sl, ls = found` → `_row(order, trade, image, sl, ls)`.

`admin_actions.resolve_attention` — replace the Skinslink-only lookup:

```python
    order, waxpeer_trade = await lock_order(db, number)
    # A Skinslink or LIS-SKINS order keeps its attention on its purchase row.
    trade: SkinTrade | PurchaseRow | None = waxpeer_trade or await purchase_of(db, order, lock=True)
```

(docstring: "order `number`'s trade (or Skinslink / LIS-SKINS purchase) attention".)

`health.py` — `from csmarket.modules.lisskins.api import LisskinsPurchase`; the three coalesces gain `LisskinsPurchase.<column>` as their third argument; `_count` adds `.outerjoin(LisskinsPurchase, LisskinsPurchase.order_id == Order.id)`; `_open_attentions` is renamed `open_attentions` (public, in `__all__`), loops over `(SkinTrade, SkinslinkPurchase, LisskinsPurchase)`, docstring "Trades and purchases of every source waiting for an admin".

`dashboard.py::_now_counts`:

```python
async def _now_counts(db: AsyncSession) -> tuple[int, int]:
    """Orders in flight and open attentions of every source, right now (one query)."""
    in_flight = (
        select(func.count()).select_from(Order).where(Order.status.in_(IN_FLIGHT)).scalar_subquery()
    )
    waiting = [
        select(func.count())
        .select_from(table)
        .where(table.attention_reason.is_not(None), table.resolved_at.is_(None))
        .scalar_subquery()
        for table in (SkinTrade, SkinslinkPurchase, LisskinsPurchase)
    ]
    a, b, c, d = (await db.execute(select(in_flight, *waiting))).one()
    return int(a), int(b) + int(c) + int(d)
```

- [ ] **Step 6: Run tests and gates**

Run: `cd apps/api && uv run pytest tests/integration/test_lisskins_status.py tests/integration/test_skinslink_status.py tests/integration/test_orders_health.py tests/integration/test_orders_read.py tests/integration/test_orders_refunds.py tests/integration/test_admin_orders_actions.py tests/integration/test_admin_dashboard.py tests/unit -q -k "not slow" && cd ../.. && make lint typecheck`
Expected: PASS; clean.

- [ ] **Step 7: Commit**

```bash
git add apps/api/src apps/api/tests
git commit -m "feat(api/orders): LIS-SKINS statuses move orders; its trade card; attentions and health count every source" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Buying from LIS-SKINS in the worker

**Files:**

- Create: `apps/api/src/csmarket/modules/orders/lisskins_writes.py`, `apps/api/src/csmarket/modules/orders/lisskins_buying.py`
- Modify: `apps/api/src/csmarket/modules/orders/buying.py:120-175` (`drain_paid` routes `lisskins` orders)
- Modify: `apps/api/src/csmarket/modules/orders/api.py` (export `attempt_lisskins_buy`)
- Test: `apps/api/tests/integration/test_orders_lisskins_buying.py`

**Interfaces:**

- Consumes: `LisskinsBuyClient`, `LisskinsError`, `LisskinsForbiddenError`, `LisskinsRateLimitedError`, `LisskinsUnavailableError`, `BUY_LINK_ERRORS`, `client_for` (Task 2); `LisskinsPurchase` (Task 3); `next_offer`, `switch_source` (Task 7); `take_lease(db, order_id, source="lisskins")` (Task 7); `apply_report` (Task 8).
- Produces in `orders/lisskins_writes.py`: `class LisskinsSnapshot(BaseModel, frozen)` with `order_id, number, skin_item_id, custom_id: str, skin_id: int, paid_units: int, cost_units: int`; `record_purchase(db, snap, report, *, outcome="bought") -> str`, `retarget(db, snap, offer) -> LisskinsSnapshot` (raises `LookupError`), `switch(db, snap, offer) -> str`, `unconfirmed(db, snap) -> str`, `secure_sent(db, snap) -> bool`, `attention(db, snap, reason, *, outcome) -> str`, `refund(db, snap, reason) -> str`.
- Produces in `orders/lisskins_buying.py`: `async attempt_lisskins_buy(db, client: LisskinsBuyClient, *, order_id: str, settings: Settings, waxpeer: TradeClient | None = None) -> str` — outcomes `bought`, `adopted`, `sold_out`, `low_balance`, `invalid_link`, `forbidden`, `rate_limited`, `unconfirmed`, `stale_bought`, `unrecorded`, `lookup_later`, `nothing_to_do`; `ATTEMPT_BUDGET`, `RELEASE_BACKOFF`.
- Produces: `drain_paid(db, *, client=None, skinslink_client=None, lisskins_client: LisskinsBuyClient | None = None, settings=None, limit=10)`.

- [ ] **Step 1: Write the failing tests**

```python
# apps/api/tests/integration/test_orders_lisskins_buying.py
"""``orders.lisskins_buying.attempt_lisskins_buy`` — spec 2026-10-07 §5 row by row.

Idempotent on our ``custom_id`` (LIS-SKINS refuses a known one); one substitute of any
source within the ceiling; a lost answer is settled by ``market/info``, never by buying
again blind; low balance, sold out and a broken trade link are refunded to the balance.
A scripted LIS-SKINS stands in; the database is real.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from csmarket.core import clock
from csmarket.core.config import Settings, get_settings
from csmarket.modules.lisskins.api import (
    LisskinsError,
    LisskinsForbiddenError,
    LisskinsRateLimitedError,
    LisskinsUnavailableError,
)
from csmarket.modules.lisskins.models import LisskinsOffer, LisskinsPurchase, LisskinsState
from csmarket.modules.orders.api import drain_paid
from csmarket.modules.orders.lisskins_buying import attempt_lisskins_buy
from csmarket.modules.orders.models import Order
from csmarket.modules.skinslink.models import SkinslinkItem, SkinslinkPurchase, SkinslinkState
from csmarket.modules.wallet.api import user_balance
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.fake_lisskins_client import FakeLisskinsClient, purchase
from tests.integration.fake_trade_client import FakeTradeClient
from tests.integration.orders_factory import make_order

PRICE = Decimal(171_800)
COST = 12_340  # LIS-SKINS prices in cents; the ceiling is 12_340 × 1.03 → 12_710
OFFER = "7252638866"


@pytest.fixture
def settings() -> Settings:
    return get_settings().model_copy(
        update={"lisskins_enabled": True, "lisskins_api_key": "k", "waxpeer_api_key": "test-key-not-real"}
    )


async def _buying(
    db: AsyncSession, *, lots: tuple[tuple[int, int], ...] = ((5, COST),), status: str = "buying"
) -> Order:
    """A kassa-paid LIS-SKINS order (lot 5) and, while ``buying``, its pending purchase."""
    order = await make_order(
        db,
        status=status,
        paid_with="payme",
        paid_at=clock.now(),
        price_uzs=PRICE,
        source="lisskins",
        offer_id="ls:5",
        listing_id=None,
        cost_units=COST,
    )
    db.add_all(
        LisskinsOffer(id=lot, skin_item_id=order.skin_item_id, price_units=units, asset_id=str(lot))
        for lot, units in lots
    )
    await db.merge(LisskinsState(id=1, snapshot_at=clock.now(), lots=len(lots)))
    if status == "buying":
        db.add(LisskinsPurchase(order_id=order.id, custom_id=order.id, skin_id=5, paid_units=COST, buy_pending=True))
    await db.commit()
    return order


async def _purchase(db: AsyncSession, order: Order) -> LisskinsPurchase:
    row = await db.scalar(
        select(LisskinsPurchase)
        .where(LisskinsPurchase.order_id == order.id)
        .execution_options(populate_existing=True)
    )
    assert row is not None
    return row


async def _order(db: AsyncSession, order: Order) -> Order:
    row = await db.scalar(select(Order).where(Order.id == order.id).execution_options(populate_existing=True))
    assert row is not None
    return row


async def test_success_records_the_purchase_and_pays_at_most_the_cost(
    db_session: AsyncSession, settings: Settings
) -> None:
    order = await _buying(db_session)
    fake = FakeLisskinsClient(purchase("processing", custom_id=order.id))
    assert await attempt_lisskins_buy(db_session, fake, order_id=order.id, settings=settings) == "bought"
    assert fake.calls == [{"skin_id": 5, "custom_id": order.id, "max_price_usd": Decimal("12.34")}]
    p = await _purchase(db_session, order)
    assert (p.purchase_id, p.status, p.buy_pending, p.amount_units) == (55, "processing", False, 12_340)
    assert (await _order(db_session, order)).status == "buying"


async def test_a_wait_accept_answer_sends_the_trade(db_session: AsyncSession, settings: Settings) -> None:
    order = await _buying(db_session)
    fake = FakeLisskinsClient(purchase("wait_accept", custom_id=order.id, offer_id=OFFER))
    assert await attempt_lisskins_buy(db_session, fake, order_id=order.id, settings=settings) == "bought"
    assert (await _order(db_session, order)).status == "trade_sent"
    assert (await _purchase(db_session, order)).steam_trade_offer_id == OFFER


async def test_a_lost_answer_is_unconfirmed_never_refunded(db_session: AsyncSession, settings: Settings) -> None:
    order = await _buying(db_session)
    fake = FakeLisskinsClient(LisskinsUnavailableError("ReadTimeout"))
    assert await attempt_lisskins_buy(db_session, fake, order_id=order.id, settings=settings) == (
        "unconfirmed"
    )
    p = await _purchase(db_session, order)
    assert (p.buy_pending, p.buy_unconfirmed_at is not None) == (False, True)
    assert (await _order(db_session, order)).status == "buying"
    assert await user_balance(db_session, order.user_id) == Decimal(0)


async def test_a_repeat_after_a_lost_answer_adopts_the_stored_purchase(
    db_session: AsyncSession, settings: Settings
) -> None:
    order = await _buying(db_session)
    stored = purchase("wait_accept", custom_id=order.id, purchase_id=77, offer_id=OFFER)
    fake = FakeLisskinsClient(
        LisskinsUnavailableError("ReadTimeout"),
        LisskinsError("known", status=400, code="custom_id_already_exists"),
        infos={order.id: stored},
    )
    await attempt_lisskins_buy(db_session, fake, order_id=order.id, settings=settings)
    # The reconcile found nothing for a while and sends the same custom id again (Task 10).
    p = await _purchase(db_session, order)
    p.buy_pending, p.buy_unconfirmed_at = True, None
    (await _order(db_session, order)).next_check_at = None
    await db_session.commit()
    assert await attempt_lisskins_buy(db_session, fake, order_id=order.id, settings=settings) == (
        "adopted"
    )
    assert [c["custom_id"] for c in fake.calls] == [order.id, order.id]
    p = await _purchase(db_session, order)
    assert (p.purchase_id, p.buy_pending) == (77, False)
    assert (await _order(db_session, order)).status == "trade_sent"


async def test_a_known_custom_id_lis_skins_cannot_show_is_unconfirmed(
    db_session: AsyncSession, settings: Settings
) -> None:
    order = await _buying(db_session)
    fake = FakeLisskinsClient(LisskinsError("known", status=400, code="custom_id_already_exists"))
    assert await attempt_lisskins_buy(db_session, fake, order_id=order.id, settings=settings) == (
        "unconfirmed"
    )


async def test_a_sold_lot_substitutes_once_then_refunds(db_session: AsyncSession, settings: Settings) -> None:
    order = await _buying(db_session, lots=((5, COST), (6, COST + 100)))
    fake = FakeLisskinsClient(
        LisskinsError("gone", status=400, code="skins_unavailable", unavailable_ids=(5,)),
        LisskinsError("dearer", status=400, code="skins_price_higher_than_max_price"),
    )
    assert await attempt_lisskins_buy(db_session, fake, order_id=order.id, settings=settings) == "sold_out"
    assert [c["skin_id"] for c in fake.calls] == [5, 6]
    assert fake.calls[1]["custom_id"] == f"{order.id}:2"
    assert fake.calls[1]["max_price_usd"] == Decimal("12.44")
    row = await _order(db_session, order)
    assert (row.status, row.failure_reason) == ("failed", "sold_out")
    assert await user_balance(db_session, order.user_id) == PRICE


async def test_a_lisskins_substitute_is_bought_under_a_second_id(
    db_session: AsyncSession, settings: Settings
) -> None:
    order = await _buying(db_session, lots=((5, COST), (6, COST + 100)))
    fake = FakeLisskinsClient(
        LisskinsError("gone", status=400, code="skins_unavailable"),
        purchase("processing", custom_id=f"{order.id}:2", purchase_id=56, id=6),
    )
    assert await attempt_lisskins_buy(db_session, fake, order_id=order.id, settings=settings) == "bought"
    p = await _purchase(db_session, order)
    assert (p.custom_id, p.skin_id, p.paid_units, p.purchase_id) == (f"{order.id}:2", 6, COST + 100, 56)


async def test_a_substitute_above_the_ceiling_is_never_bought(
    db_session: AsyncSession, settings: Settings
) -> None:
    order = await _buying(db_session, lots=((5, COST), (6, 12_711)))
    fake = FakeLisskinsClient(LisskinsError("gone", status=400, code="skins_unavailable"))
    assert await attempt_lisskins_buy(db_session, fake, order_id=order.id, settings=settings) == "sold_out"
    assert len(fake.calls) == 1


async def test_a_skinslink_substitute_hands_the_order_to_the_skinslink_path(
    db_session: AsyncSession, settings: Settings
) -> None:
    order = await _buying(db_session)
    db_session.add(
        SkinslinkItem(id="100", market_hash_name=order.market_hash_name, phase="", price_units=COST, skin_item_id=order.skin_item_id)
    )
    await db_session.merge(SkinslinkState(id=1, cursor="c", mirror_synced_at=clock.now()))
    await db_session.commit()
    on = settings.model_copy(update={"skinslink_enabled": True, "skinslink_api_key": "k", "skinslink_secret": "s"})
    fake = FakeLisskinsClient(LisskinsError("gone", status=400, code="skins_unavailable"))
    assert await attempt_lisskins_buy(db_session, fake, order_id=order.id, settings=on) == "lookup_later"
    row = await _order(db_session, order)
    assert (row.source, row.offer_id, row.status) == ("skinslink", "sl:100", "buying")
    sl = await db_session.scalar(select(SkinslinkPurchase).where(SkinslinkPurchase.order_id == order.id))
    assert sl is not None and sl.merchant_tx_id == f"{order.id}:2"


@pytest.mark.parametrize(
    ("code", "reason"),
    [
        ("insufficient_funds", "source_low_balance"),
        ("invalid_trade_url", "invalid_trade_link"),
        ("user_trade_ban", "invalid_trade_link"),
        ("user_cant_trade", "invalid_trade_link"),
        ("private_inventory", "invalid_trade_link"),
        ("too_many_failed_attempts_for_user", "invalid_trade_link"),
        ("invalid_partner_value", "invalid_trade_link"),
    ],
)
async def test_refund_reasons(db_session: AsyncSession, settings: Settings, code: str, reason: str) -> None:
    order = await _buying(db_session, lots=((5, COST), (6, COST)))
    status = 422 if code.startswith("invalid_partner") else 400
    fake = FakeLisskinsClient(LisskinsError("no", status=status, code=code))
    await attempt_lisskins_buy(db_session, fake, order_id=order.id, settings=settings)
    row = await _order(db_session, order)
    assert (row.status, row.failure_reason) == ("failed", reason)
    assert len(fake.calls) == 1  # never a substitute: every lot would be refused the same way
    assert await user_balance(db_session, order.user_id) == PRICE


async def test_forbidden_is_an_attention_and_keeps_the_buy_pending(
    db_session: AsyncSession, settings: Settings
) -> None:
    order = await _buying(db_session)
    fake = FakeLisskinsClient(LisskinsForbiddenError("forbidden", status=401))
    assert await attempt_lisskins_buy(db_session, fake, order_id=order.id, settings=settings) == "forbidden"
    p = await _purchase(db_session, order)
    assert (p.attention_reason, p.buy_pending) == ("source_forbidden", True)


async def test_429_waits_for_its_retry_after(db_session: AsyncSession, settings: Settings) -> None:
    order = await _buying(db_session)
    fake = FakeLisskinsClient(LisskinsRateLimitedError("slow", retry_after=45))
    assert await attempt_lisskins_buy(db_session, fake, order_id=order.id, settings=settings) == (
        "rate_limited"
    )
    assert (await _purchase(db_session, order)).buy_pending is True
    row = await _order(db_session, order)
    assert row.next_check_at is not None and row.next_check_at >= clock.now() + timedelta(seconds=44)


async def test_a_rerun_after_the_substitute_never_substitutes_again(
    db_session: AsyncSession, settings: Settings
) -> None:
    order = await _buying(db_session, lots=((5, COST), (6, 12_400), (7, 12_500)))
    p = await _purchase(db_session, order)
    p.custom_id, p.skin_id, p.paid_units = f"{order.id}:2", 6, 12_400
    await db_session.commit()
    fake = FakeLisskinsClient(LisskinsError("gone", status=400, code="skins_unavailable"))
    assert await attempt_lisskins_buy(db_session, fake, order_id=order.id, settings=settings) == "sold_out"
    assert [c["custom_id"] for c in fake.calls] == [f"{order.id}:2"]


async def test_a_settled_buy_is_never_bought_again(db_session: AsyncSession, settings: Settings) -> None:
    order = await _buying(db_session)
    fake = FakeLisskinsClient(purchase("processing", custom_id=order.id))
    await attempt_lisskins_buy(db_session, fake, order_id=order.id, settings=settings)
    assert await attempt_lisskins_buy(db_session, fake, order_id=order.id, settings=settings) == (
        "nothing_to_do"
    )
    assert len(fake.calls) == 1


async def test_an_unreadable_trade_link_refunds_without_a_call(
    db_session: AsyncSession, settings: Settings
) -> None:
    order = await _buying(db_session)
    row = await _order(db_session, order)
    row.trade_link = "not a trade link"
    await db_session.commit()
    fake = FakeLisskinsClient()
    assert await attempt_lisskins_buy(db_session, fake, order_id=order.id, settings=settings) == (
        "invalid_link"
    )
    assert fake.calls == []


async def test_drain_paid_buys_a_lisskins_order(db_session: AsyncSession, settings: Settings) -> None:
    order = await _buying(db_session, status="paid")
    fake = FakeLisskinsClient(purchase("processing", custom_id=order.id))
    claimed = await drain_paid(db_session, client=FakeTradeClient(), lisskins_client=fake, settings=settings)
    assert claimed == 1
    assert fake.calls[0]["custom_id"] == order.id
    p = await _purchase(db_session, order)
    assert (p.skin_id, p.paid_units, p.buy_pending) == (5, COST, False)
```

- [ ] **Step 2: Run them**

Run: `cd apps/api && uv run pytest tests/integration/test_orders_lisskins_buying.py -q`
Expected: FAIL — `ModuleNotFoundError: csmarket.modules.orders.lisskins_buying`.

- [ ] **Step 3: Write `orders/lisskins_writes.py`**

```python
"""The LIS-SKINS buy's writes (``orders.lisskins_buying``): lock the order, then its purchase
(ruling K), re-check ``status == "buying"`` and ``buy_pending``, write, commit — and write
nothing when a sweep moved the rows during the LIS-SKINS call. Each returns the outcome.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.logging import get_logger
from csmarket.core.metrics import TradeAttentionReason
from csmarket.modules.lisskins.api import LisskinsPurchase, Purchase
from csmarket.modules.orders.lisskins_status import apply_report
from csmarket.modules.orders.models import Order
from csmarket.modules.orders.refunds import refund_to_balance
from csmarket.modules.orders.substitutes import switch_source
from csmarket.modules.orders.trades import flag
from csmarket.modules.skins.api import Offer, parse_offer_id

log = get_logger("csmarket.orders.lisskins_buying")

_ACTOR = "orders"
#: Refund reason → outcome.
_REFUND_OUTCOMES: dict[str, str] = {
    "invalid_trade_link": "invalid_link",
    "sold_out": "sold_out",
    "source_low_balance": "low_balance",
}


class LisskinsSnapshot(BaseModel):
    """What a LIS-SKINS buy needs of the order, read unlocked before LIS-SKINS is called."""

    model_config = ConfigDict(frozen=True)

    order_id: str
    number: str
    skin_item_id: str
    custom_id: str
    skin_id: int
    paid_units: int
    #: The order's agreed cost: the substitute ceiling is counted from it.
    cost_units: int


async def _lock_both(
    db: AsyncSession, order_id: str
) -> tuple[Order | None, LisskinsPurchase | None]:
    order = await db.scalar(
        select(Order).where(Order.id == order_id).with_for_update().execution_options(populate_existing=True)
    )
    purchase = await db.scalar(
        select(LisskinsPurchase)
        .where(LisskinsPurchase.order_id == order_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return order, purchase


async def _locked(
    db: AsyncSession, snap: LisskinsSnapshot
) -> tuple[Order, LisskinsPurchase] | None:
    """Both rows ``FOR UPDATE`` if still ``buying`` with the buy pending; else ``None``."""
    order, purchase = await _lock_both(db, snap.order_id)
    if order is None or purchase is None or order.status != "buying" or not purchase.buy_pending:
        await db.commit()  # nothing written: just let the locks go
        return None
    return order, purchase


def _stale(snap: LisskinsSnapshot, outcome: str) -> str:
    """Someone moved the rows during the call, and nothing was bought: write nothing."""
    log.warning("orders.lisskins_buy.stale", number=snap.number, outcome=outcome)
    return "nothing_to_do"


async def _stale_purchase(db: AsyncSession, snap: LisskinsSnapshot) -> str:
    """A purchase that may have gone through landed on moved rows: flagged, never silent."""
    order, purchase = await _lock_both(db, snap.order_id)
    if order is not None and purchase is not None:
        flag(purchase, "ambiguous_trade", reopen=True)
    await db.commit()
    log.error("orders.lisskins_buy.stale_purchase", number=snap.number)
    return "stale_bought"


def _settle(purchase: LisskinsPurchase) -> None:
    """The buy is no longer pending; a ``source_forbidden`` attention is moot now."""
    purchase.buy_pending = False
    if purchase.attention_reason == "source_forbidden":
        purchase.attention_reason = None
        purchase.resolved_at = purchase.resolved_by = purchase.resolved_note = None
    purchase.updated_at = now()


async def record_purchase(
    db: AsyncSession, snap: LisskinsSnapshot, report: Purchase, *, outcome: str = "bought"
) -> str:
    """LIS-SKINS took the purchase (or ``market/info`` named it): record it, apply its status."""
    pair = await _locked(db, snap)
    if pair is None:
        return await _stale_purchase(db, snap)
    order, purchase = pair
    _settle(purchase)
    purchase.buy_unconfirmed_at = None
    await apply_report(db, order=order, purchase=purchase, report=report)
    await db.commit()
    return outcome


async def retarget(db: AsyncSession, snap: LisskinsSnapshot, offer: Offer) -> LisskinsSnapshot:
    """Point the purchase at a LIS-SKINS substitute under ``<order id>:2``, committed before
    the request goes out — a lost answer is then settled under the id actually used.

    Raises:
        LookupError: The order left ``buying`` meanwhile.
    """
    pair = await _locked(db, snap)
    if pair is None:
        raise LookupError("the order left buying")
    _, purchase = pair
    key, skin_id = f"{snap.order_id}:2", int(parse_offer_id(offer.offer_id)[1])
    purchase.custom_id, purchase.skin_id, purchase.paid_units = key, skin_id, offer.price_units
    purchase.updated_at = now()
    await db.commit()
    return snap.model_copy(
        update={"custom_id": key, "skin_id": skin_id, "paid_units": offer.price_units}
    )


async def switch(db: AsyncSession, snap: LisskinsSnapshot, offer: Offer) -> str:
    """A substitute of another source: that source's path buys it next; this row goes."""
    pair = await _locked(db, snap)
    if pair is None or (offer.source == "waxpeer" and offer.listing_id is None):
        return _stale(snap, "lookup_later")
    await switch_source(db, pair[0], offer)
    await db.commit()
    log.info("orders.lisskins_buy.switched", number=snap.number, source=offer.source)
    return "lookup_later"


async def unconfirmed(db: AsyncSession, snap: LisskinsSnapshot) -> str:
    """The answer was lost: the reconcile settles it by ``market/info`` (never a blind rebuy)."""
    pair = await _locked(db, snap)
    if pair is None:
        return await _stale_purchase(db, snap)
    _, purchase = pair
    _settle(purchase)
    purchase.buy_unconfirmed_at = now()
    await db.commit()
    return "unconfirmed"


async def secure_sent(db: AsyncSession, snap: LisskinsSnapshot) -> bool:
    """A buy this attempt sent but could not record: never leave it ``buy_pending``."""
    order, purchase = await _lock_both(db, snap.order_id)
    marked = order is not None and purchase is not None and purchase.buy_pending
    if marked and order is not None and purchase is not None:
        _settle(purchase)
        purchase.buy_unconfirmed_at = now()
        if order.status != "buying":
            flag(purchase, "ambiguous_trade", reopen=True)
    await db.commit()
    return marked


async def attention(
    db: AsyncSession, snap: LisskinsSnapshot, reason: TradeAttentionReason, *, outcome: str
) -> str:
    """Flag the purchase for an admin; the buy stays pending."""
    pair = await _locked(db, snap)
    if pair is None:
        return _stale(snap, outcome)
    flag(pair[1], reason, reopen=True)
    await db.commit()
    return outcome


async def refund(db: AsyncSession, snap: LisskinsSnapshot, reason: str) -> str:
    """Nothing was bought: ``failed`` and the money back to the balance (R9)."""
    pair = await _locked(db, snap)
    if pair is None:
        return _stale(snap, _REFUND_OUTCOMES[reason])
    order, purchase = pair
    try:
        _settle(purchase)
        await refund_to_balance(db, order=order, to_status="failed", reason=reason, actor=_ACTOR)
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return _REFUND_OUTCOMES[reason]


__all__ = [
    "LisskinsSnapshot",
    "attention",
    "record_purchase",
    "refund",
    "retarget",
    "secure_sent",
    "switch",
    "unconfirmed",
]
```

- [ ] **Step 4: Write `orders/lisskins_buying.py`**

```python
"""The worker buys a paid LIS-SKINS order — at most once (spec 2026-10-07 §5).

:func:`attempt_lisskins_buy` has the Skinslink path's shape (``orders.skinslink_buying``):

1. take the order's lease (``take_lease(..., source="lisskins")``), then read the snapshot;
2. a trade link that does not parse → refund ``invalid_trade_link``;
3. ``POST /market/buy`` for the one lot, keyed by our ``custom_id`` (the order id), with
   ``max_price`` = the agreed cost. LIS-SKINS refuses a ``custom_id`` it knows, so a repeat
   never buys twice: ``custom_id_already_exists`` is answered from ``market/info`` and the
   stored purchase adopted;
4. sold or dearer than our cap → the cheapest other offer of any source within the
   ceiling, once (``orders.substitutes``: a LIS-SKINS one under ``<order id>:2``, another
   source's hands the order to that path); ``insufficient_funds`` → refund
   ``source_low_balance``; a refusal naming the trade link → refund ``invalid_trade_link``;
   401/403 → attention ``source_forbidden``, the buy kept pending; 429 → retried after its
   ``Retry-After``; no answer, a timeout or a 5xx → ``buy_unconfirmed_at``, settled by the
   reconcile's ``market/info`` (``orders.lisskins_reconcile``).

No lock is held across a LIS-SKINS call (``orders.lisskins_writes``). Log lines carry the
order number and the outcome, never the trade link.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from decimal import Decimal
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.config import Settings
from csmarket.core.errors import ValidationError
from csmarket.core.logging import get_logger
from csmarket.core.metrics import OrderBuyOutcome, record_order_buy
from csmarket.modules.lisskins.api import (
    BUY_LINK_ERRORS,
    LisskinsBuyClient,
    LisskinsError,
    LisskinsForbiddenError,
    LisskinsPurchase,
    LisskinsRateLimitedError,
    LisskinsUnavailableError,
)
from csmarket.modules.orders.buy_lease import BUY_LEASE, discard, release, release_fresh, take_lease
from csmarket.modules.orders.lisskins_writes import (
    LisskinsSnapshot,
    attention,
    record_purchase,
    refund,
    retarget,
    secure_sent,
    switch,
    unconfirmed,
)
from csmarket.modules.orders.models import Order
from csmarket.modules.orders.substitutes import next_offer
from csmarket.modules.skins.api import TradeClient, offer_id_of
from csmarket.modules.users.api import TradeLink, parse_tradelink

log = get_logger("csmarket.orders.lisskins_buying")

#: An attempt's time budget, counted from before its lease is taken.
ATTEMPT_BUDGET = BUY_LEASE - timedelta(seconds=30)
#: How long the order waits after a 401/403 or a 429 before the next attempt.
RELEASE_BACKOFF: dict[str, timedelta] = {
    "forbidden": timedelta(seconds=60),
    "rate_limited": timedelta(seconds=20),
}
#: The longest a 429's own ``Retry-After`` may hold an order.
MAX_RETRY_AFTER = BUY_LEASE
_UNCOUNTED = frozenset({"nothing_to_do", "lookup_later"})
_SECURE_SECONDS = 10.0
_UNITS_PER_USD = Decimal(1000)


class _Run:
    """One attempt's progress: its snapshot, whether a request went out, a 429's wait."""

    __slots__ = ("retry_after", "sent", "snap")

    def __init__(self) -> None:
        self.snap: LisskinsSnapshot | None = None
        self.sent = False
        self.retry_after: float | None = None

    def backoff(self, outcome: str) -> timedelta:
        """:data:`RELEASE_BACKOFF`, or LIS-SKINS' own ``Retry-After`` when longer (capped)."""
        wait = RELEASE_BACKOFF.get(outcome, timedelta(0))
        if self.retry_after is not None and wait > timedelta(0):
            wait = max(wait, min(timedelta(seconds=self.retry_after), MAX_RETRY_AFTER))
        return wait


async def attempt_lisskins_buy(
    db: AsyncSession,
    client: LisskinsBuyClient,
    *,
    order_id: str,
    settings: Settings,
    waxpeer: TradeClient | None = None,
) -> str:
    """Buy order ``order_id`` at LIS-SKINS, unless it was bought or is being bought.

    Args:
        db: Session; each step commits its own short transaction.
        client: LIS-SKINS (the buy timeout).
        order_id: The order.
        settings: For the substitute ceiling and the listings budget.
        waxpeer: Waxpeer, for a substitute among its listings; ``None`` looks at our own
            tables only.

    Returns:
        ``bought``, ``adopted``, ``sold_out``, ``low_balance``, ``invalid_link``,
        ``forbidden``, ``rate_limited``, ``unconfirmed``, ``stale_bought``, ``unrecorded``,
        ``lookup_later`` (handed to another source's path) or ``nothing_to_do``.
    """
    deadline = asyncio.get_running_loop().time() + ATTEMPT_BUDGET.total_seconds()
    lease = await take_lease(db, order_id, source="lisskins")
    if lease is None:
        return "nothing_to_do"
    run = _Run()
    try:
        async with asyncio.timeout_at(deadline):
            outcome = await _leased(
                db, client, order_id=order_id, settings=settings, waxpeer=waxpeer, run=run
            )
    except TimeoutError:
        outcome = await _after_timeout(db, order_id=order_id, lease=lease, run=run)
    except BaseException:
        if run.sent and run.snap is not None:
            await discard(db)
            await _secure(db, run.snap)
        raise
    else:
        await release(db, order_id, lease, after=run.backoff(outcome))
    if run.snap is None:
        return outcome
    if outcome not in _UNCOUNTED:
        record_order_buy(cast(OrderBuyOutcome, outcome))  # every other outcome is in the set
    log.info("orders.lisskins_buy", number=run.snap.number, outcome=outcome)
    return outcome


async def _secure(db: AsyncSession, snap: LisskinsSnapshot) -> bool | None:
    """Record a sent buy as unconfirmed through a fresh session; ``None`` on failure."""
    try:
        async with (
            asyncio.timeout(_SECURE_SECONDS),
            AsyncSession(bind=db.bind, expire_on_commit=False) as fresh,
        ):
            return await secure_sent(fresh, snap)
    except Exception as exc:  # noqa: BLE001 -- keep the lease; the error is logged
        log.error("orders.lisskins_buy.unrecorded", number=snap.number, error=type(exc).__name__)  # noqa: TRY400
        return None


async def _after_timeout(db: AsyncSession, *, order_id: str, lease: datetime, run: _Run) -> str:
    """The budget ran out: nothing sent → due again; a sent buy → unconfirmed."""
    await discard(db)
    if not run.sent or run.snap is None:
        await release_fresh(db, order_id, lease)
        return "lookup_later"
    marked = await _secure(db, run.snap)
    if marked is None:
        return "unrecorded"
    await release_fresh(db, order_id, lease)
    return "unconfirmed" if marked else "nothing_to_do"


async def _leased(
    db: AsyncSession,
    client: LisskinsBuyClient,
    *,
    order_id: str,
    settings: Settings,
    waxpeer: TradeClient | None,
    run: _Run,
) -> str:
    """Read the snapshot under the lease, then buy."""
    order = await db.scalar(
        select(Order).where(Order.id == order_id).execution_options(populate_existing=True)
    )
    purchase = await db.scalar(
        select(LisskinsPurchase)
        .where(LisskinsPurchase.order_id == order_id)
        .execution_options(populate_existing=True)
    )
    await db.commit()
    if order is None or purchase is None or order.status != "buying" or not purchase.buy_pending:
        return "nothing_to_do"
    run.snap = LisskinsSnapshot(
        order_id=order.id,
        number=order.number,
        skin_item_id=order.skin_item_id,
        custom_id=purchase.custom_id,
        skin_id=purchase.skin_id,
        paid_units=purchase.paid_units,
        cost_units=order.cost_units,
    )
    try:
        link = parse_tradelink(order.trade_link)
    except ValidationError:
        return await refund(db, run.snap, "invalid_trade_link")
    return await _buy(db, client, link=link, settings=settings, waxpeer=waxpeer, run=run)


async def _buy(
    db: AsyncSession,
    client: LisskinsBuyClient,
    *,
    link: TradeLink,
    settings: Settings,
    waxpeer: TradeClient | None,
    run: _Run,
) -> str:
    """The chosen lot at the agreed units, then at most one substitute per order: a rerun
    after the substitute was taken (``<id>:2``) never looks for another."""
    assert run.snap is not None
    snap = run.snap
    ceiling = int(snap.cost_units * (1 + settings.order_substitute_ceiling))
    tried = {offer_id_of("lisskins", snap.skin_id)}
    first = 1 if snap.custom_id == snap.order_id else 2
    for attempt in range(first, 3):
        settled = await _buy_once(db, client, snap, link, run)
        if settled is not None:
            return settled
        if attempt == 2:
            break
        log.info("orders.lisskins_buy.refused", number=snap.number)
        nxt = await next_offer(
            db,
            skin_item_id=snap.skin_item_id,
            ceiling=ceiling,
            tried=tried,
            settings=settings,
            waxpeer=waxpeer,
        )
        if nxt is None:
            break
        if nxt.source != "lisskins":
            return await switch(db, snap, nxt)
        tried.add(nxt.offer_id)
        try:
            snap = run.snap = await retarget(db, snap, nxt)
        except LookupError:
            return "nothing_to_do"
    return await refund(db, snap, "sold_out")


async def _buy_once(  # noqa: PLR0911 -- one return per row of the spec's table
    db: AsyncSession,
    client: LisskinsBuyClient,
    snap: LisskinsSnapshot,
    link: TradeLink,
    run: _Run,
) -> str | None:
    """One buy request: the attempt's outcome, or ``None`` for a lot that cannot be had."""
    try:
        run.sent = True  # from here on an unrecorded exit must not free the order
        report = await client.buy(
            skin_id=snap.skin_id,
            partner=link.partner,
            token=link.token,
            max_price_usd=Decimal(snap.paid_units) / _UNITS_PER_USD,
            custom_id=snap.custom_id,
        )
    except LisskinsForbiddenError:
        return await attention(db, snap, "source_forbidden", outcome="forbidden")
    except LisskinsRateLimitedError as exc:
        run.retry_after = exc.retry_after
        return "rate_limited"
    except LisskinsUnavailableError:
        return await unconfirmed(db, snap)  # it may have gone through: market/info settles it
    except LisskinsError as err:
        if err.code == "custom_id_already_exists":
            return await _adopt(db, client, snap)
        if err.code in BUY_LINK_ERRORS:
            return await refund(db, snap, "invalid_trade_link")
        if err.code == "insufficient_funds":
            return await refund(db, snap, "source_low_balance")
        return None  # sold, dearer than our cap, or another refusal of this lot
    return await record_purchase(db, snap, report)


async def _adopt(db: AsyncSession, client: LisskinsBuyClient, snap: LisskinsSnapshot) -> str:
    """LIS-SKINS knows our ``custom_id``: take its stored purchase, or leave it to the
    reconcile when ``market/info`` cannot show it now."""
    try:
        found = await client.info(custom_ids=[snap.custom_id])
    except (LisskinsError, LisskinsUnavailableError):
        found = []
    report = next((p for p in found if p.custom_id == snap.custom_id), None)
    if report is None:
        return await unconfirmed(db, snap)
    return await record_purchase(db, snap, report, outcome="adopted")


__all__ = ["ATTEMPT_BUDGET", "MAX_RETRY_AFTER", "RELEASE_BACKOFF", "attempt_lisskins_buy"]
```

- [ ] **Step 5: Route LIS-SKINS orders in `drain_paid`**

`buying.py` — imports `from csmarket.modules.lisskins.api import LisskinsBuyClient` and `from csmarket.modules.lisskins.api import client_for as lisskins_client_for`, `from csmarket.modules.orders.lisskins_buying import attempt_lisskins_buy`; the signature gains `lisskins_client: LisskinsBuyClient | None = None,` after `skinslink_client` (docstring: "LIS-SKINS; built (buy timeout) when a LIS-SKINS order is claimed"); the loop:

```python
            if source == "skinslink":
                ...  # unchanged
            elif source == "lisskins":
                lisskins_client = lisskins_client or lisskins_client_for(
                    settings, timeout_seconds=settings.lisskins_buy_timeout_seconds
                )
                await attempt_lisskins_buy(
                    db, lisskins_client, order_id=order_id, settings=settings, waxpeer=client
                )
            else:
                await attempt_buy(db, client, order_id=order_id, settings=settings)
```

`orders/api.py` exports `attempt_lisskins_buy`.

- [ ] **Step 6: Run tests and gates**

Run: `cd apps/api && uv run pytest tests/integration/test_orders_lisskins_buying.py tests/integration/test_orders_buying_drain.py tests/integration/test_orders_skinslink_buying.py tests/integration/test_orders_buying.py -q && cd ../worker && uv run pytest tests -q && cd ../.. && make lint typecheck`
Expected: PASS; clean.

- [ ] **Step 7: Commit**

```bash
git add apps/api/src apps/api/tests
git commit -m "feat(api/orders): the worker buys LIS-SKINS orders once per custom id; one substitute of any source" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: The reconcile — one `market/info` call per tick, the unconfirmed rule, trade protection

Decisions: delivered orders whose purchase LIS-SKINS reported `accepted` stay polled (every 10 minutes) for 8 days — Steam's trade protection — or a `rollback_…` return would never be seen (spec §6 needs it); open orders are asked before protected ones when more than 200 are due; a purchase we hold a `purchase_id` for is never settled by its absence from an answer.

**Files:**

- Create: `apps/api/src/csmarket/modules/orders/lisskins_reconcile.py`; modify `orders/api.py` (export `reconcile_lisskins`)
- Create: `apps/scheduler/src/csmarket_scheduler/jobs/lisskins_reconcile.py`; modify `apps/scheduler/src/csmarket_scheduler/main.py`, `apps/scheduler/tests/test_main.py` (`"lisskins.reconcile"` after `"lisskins.snapshot"`)
- Test: `apps/api/tests/integration/test_lisskins_reconcile.py`, `apps/scheduler/tests/test_lisskins_reconcile.py`

**Interfaces:**

- Consumes: `LisskinsBuyClient`, `INFO_MAX_IDS`, `client_for` (Task 2); `attempt_lisskins_buy` (Task 9); `apply_report`, `lock` (Task 8).
- Produces in `orders/lisskins_reconcile.py`: `PROTECTION = timedelta(days=8)`, `PROTECTION_POLL_EVERY = timedelta(minutes=10)`, `BUY_BATCH = 20`; `async apply_polled(db, *, order_id: str, custom_id: str, report: Purchase | None, settings: Settings) -> str` (commits; outcomes of `apply_report`, plus `repeat`); `async reconcile_lisskins(db_factory: Callable[[], AsyncSession], client: LisskinsBuyClient, *, settings: Settings, waxpeer: TradeClient | None = None) -> int` (orders looked at).
- Produces: scheduler job `lisskins.reconcile` every 30 s (first run 340 s), skipped without `lisskins_api_key` — the key, not the switch: open orders settle after a switch-off.

- [ ] **Step 1: Write the failing tests**

```python
# apps/api/tests/integration/test_lisskins_reconcile.py
"""The LIS-SKINS reconcile: one ``market/info`` call for every due purchase, the unconfirmed
rule, Steam's trade protection, a failed call, a pending buy."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from csmarket.core import clock
from csmarket.core.config import get_settings
from csmarket.modules.lisskins.api import LisskinsUnavailableError
from csmarket.modules.lisskins.models import LisskinsPurchase
from csmarket.modules.orders import lisskins_reconcile
from csmarket.modules.orders.lisskins_reconcile import reconcile_lisskins
from csmarket.modules.orders.models import Order
from csmarket.modules.wallet.api import user_balance
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.integration.fake_lisskins_client import FakeLisskinsClient, purchase
from tests.integration.lisskins_factory import OFFER, PRICE, make_lisskins_order

SETTINGS = get_settings().model_copy(update={"lisskins_enabled": True, "lisskins_api_key": "k"})


async def _tick(engine: AsyncEngine, fake: FakeLisskinsClient) -> int:
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    return await reconcile_lisskins(factory, fake, settings=SETTINGS)


async def _state(db: AsyncSession, order: Order) -> tuple[Order, LisskinsPurchase]:
    row = await db.scalar(select(Order).where(Order.id == order.id).execution_options(populate_existing=True))
    p = await db.scalar(
        select(LisskinsPurchase)
        .where(LisskinsPurchase.order_id == order.id)
        .execution_options(populate_existing=True)
    )
    assert row is not None and p is not None
    return row, p


async def test_one_info_call_for_every_open_purchase(
    db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    a, _ = await make_lisskins_order(db_session, status="buying", skin_status="processing")
    b, _ = await make_lisskins_order(db_session)
    c, _ = await make_lisskins_order(db_session)
    fake = FakeLisskinsClient(
        infos={
            a.id: purchase("wait_accept", custom_id=a.id, offer_id=OFFER),
            b.id: purchase("accepted", custom_id=b.id),
            c.id: purchase("return", custom_id=c.id, return_reason="trade_timeout"),
        }
    )
    assert await _tick(db_engine, fake) == 3
    assert len(fake.info_calls) == 1
    assert sorted(fake.info_calls[0]) == sorted([a.id, b.id, c.id])
    assert [(await _state(db_session, o))[0].status for o in (a, b, c)] == [
        "trade_sent",
        "delivered",
        "returned",
    ]
    assert await user_balance(db_session, c.user_id) == PRICE


async def test_open_orders_are_asked_before_protected_ones(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    monkeypatch.setattr(lisskins_reconcile, "INFO_MAX_IDS", 2)
    for _ in range(2):
        await make_lisskins_order(
            db_session,
            status="delivered",
            skin_status="accepted",
            order={"delivered_at": clock.now() - timedelta(days=1)},
            last_polled_at=clock.now() - timedelta(hours=1),
        )
    fresh, _ = await make_lisskins_order(db_session, last_polled_at=clock.now() - timedelta(seconds=40))
    fake = FakeLisskinsClient()
    await _tick(db_engine, fake)
    assert len(fake.info_calls[0]) == 2 and fresh.id in fake.info_calls[0]


async def test_an_unconfirmed_buy_found_is_adopted(
    db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    order, _ = await make_lisskins_order(
        db_session,
        status="buying",
        skin_status=None,
        purchase_id=None,
        buy_unconfirmed_at=clock.now() - timedelta(minutes=1),
    )
    fake = FakeLisskinsClient(infos={order.id: purchase("processing", custom_id=order.id, purchase_id=77)})
    await _tick(db_engine, fake)
    _, p = await _state(db_session, order)
    assert (p.purchase_id, p.buy_unconfirmed_at, p.status) == (77, None, "processing")


async def test_an_unseen_buy_is_bought_again_under_the_same_custom_id_after_the_wait(
    db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    lost = clock.now() - timedelta(minutes=get_settings().order_unconfirmed_minutes + 1)
    order, _ = await make_lisskins_order(
        db_session, status="buying", skin_status=None, purchase_id=None, buy_unconfirmed_at=lost
    )
    fake = FakeLisskinsClient(purchase("processing", custom_id=order.id))
    await _tick(db_engine, fake)  # LIS-SKINS shows nothing under our id: due again
    _, p = await _state(db_session, order)
    assert (p.buy_pending, p.buy_unconfirmed_at) == (True, None)
    await _tick(db_engine, fake)
    assert [c["custom_id"] for c in fake.calls] == [order.id]
    _, p = await _state(db_session, order)
    assert (p.buy_pending, p.purchase_id) == (False, 55)


async def test_unseen_before_the_wait_is_left_alone(
    db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    order, _ = await make_lisskins_order(
        db_session,
        status="buying",
        skin_status=None,
        purchase_id=None,
        buy_unconfirmed_at=clock.now() - timedelta(minutes=1),
    )
    fake = FakeLisskinsClient()
    await _tick(db_engine, fake)
    _, p = await _state(db_session, order)
    assert (p.buy_pending, p.buy_unconfirmed_at is not None, fake.calls) == (False, True, [])


async def test_a_known_purchase_missing_from_info_is_left_alone(
    db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    order, _ = await make_lisskins_order(db_session)  # purchase 55, offer sent
    fake = FakeLisskinsClient()  # info answers without it
    await _tick(db_engine, fake)
    row, p = await _state(db_session, order)
    assert (row.status, p.buy_pending, p.attention_reason) == ("trade_sent", False, None)
    assert fake.calls == []
    assert await user_balance(db_session, order.user_id) == Decimal(0)


async def test_a_rollback_after_delivery_is_seen_by_the_protection_poll(
    db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    order, _ = await make_lisskins_order(
        db_session,
        status="delivered",
        skin_status="accepted",
        order={"delivered_at": clock.now() - timedelta(days=2)},
        last_polled_at=clock.now() - timedelta(minutes=11),
    )
    await make_lisskins_order(  # past the protection: never asked again
        db_session,
        status="delivered",
        skin_status="accepted",
        order={"delivered_at": clock.now() - timedelta(days=9)},
        last_polled_at=clock.now() - timedelta(days=1),
    )
    await make_lisskins_order(  # asked 2 minutes ago: waits
        db_session,
        status="delivered",
        skin_status="accepted",
        order={"delivered_at": clock.now() - timedelta(days=1)},
        last_polled_at=clock.now() - timedelta(minutes=2),
    )
    fake = FakeLisskinsClient(
        infos={order.id: purchase("return", custom_id=order.id, return_reason="rollback_user")}
    )
    await _tick(db_engine, fake)
    assert fake.info_calls == [[order.id]]
    row, p = await _state(db_session, order)
    assert (row.status, p.attention_reason) == ("delivered", "rolled_back")
    assert await user_balance(db_session, order.user_id) == Decimal(0)


async def test_a_failed_info_call_changes_nothing(
    db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    order, _ = await make_lisskins_order(db_session)
    fake = FakeLisskinsClient(info_error=LisskinsUnavailableError("down"))
    await _tick(db_engine, fake)
    row, p = await _state(db_session, order)
    assert (row.status, p.last_polled_at) == ("trade_sent", None)


async def test_a_pending_buy_is_bought_by_the_tick(
    db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    order, _ = await make_lisskins_order(
        db_session, status="buying", skin_status=None, purchase_id=None, buy_pending=True
    )
    fake = FakeLisskinsClient(purchase("processing", custom_id=order.id))
    await _tick(db_engine, fake)
    assert [c["custom_id"] for c in fake.calls] == [order.id]
    assert fake.info_calls == []  # it was not due a poll in the same tick
```

```python
# apps/scheduler/tests/test_lisskins_reconcile.py
"""``lisskins.reconcile``: runs with a key even when switched off, never raises, every 30 s."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from csmarket.core.config import get_settings
from csmarket_scheduler.jobs import lisskins_reconcile as job


def _settings(monkeypatch: pytest.MonkeyPatch, **update: object) -> None:
    s = get_settings().model_copy(update=update)
    monkeypatch.setattr(job, "get_settings", lambda: s)


async def test_without_a_key_nothing_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    tick = AsyncMock()
    monkeypatch.setattr(job, "reconcile_lisskins", tick)
    _settings(monkeypatch, lisskins_api_key="")
    await job.run()
    tick.assert_not_awaited()


async def test_a_key_is_enough_to_settle_open_orders(monkeypatch: pytest.MonkeyPatch) -> None:
    tick = AsyncMock(return_value=0)
    monkeypatch.setattr(job, "reconcile_lisskins", tick)
    _settings(monkeypatch, lisskins_api_key="k", lisskins_enabled=False)
    await job.run()
    tick.assert_awaited_once()


async def test_a_failure_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(job, "reconcile_lisskins", AsyncMock(side_effect=RuntimeError("boom")))
    _settings(monkeypatch, lisskins_api_key="k")
    await job.run()


def test_registers_every_30_seconds() -> None:
    scheduler = AsyncIOScheduler()
    job.register(scheduler)
    registered = scheduler.get_job(job.JOB_ID)
    assert registered is not None and registered.trigger.interval.total_seconds() == 30
```

- [ ] **Step 2: Run them**

Run: `cd apps/api && uv run pytest tests/integration/test_lisskins_reconcile.py -q; cd ../scheduler && uv run pytest tests/test_lisskins_reconcile.py -q`
Expected: FAIL — `ModuleNotFoundError` for `orders.lisskins_reconcile` and the job.

- [ ] **Step 3: Write `orders/lisskins_reconcile.py`**

```python
"""The LIS-SKINS reconcile (spec 2026-10-07 §6): statuses are polled; there is no webhook.

Every 30 s (``lisskins.reconcile``): a LIS-SKINS order whose buy is pending is bought
(``lisskins_buying``; its lease decides whether anyone else is on it); every other open one —
and a delivered one inside Steam's trade protection, where a rollback can still come — is
asked about in **one** ``GET /market/info`` call by our ``custom_id`` (≤ 200, open ones
first). A purchase LIS-SKINS does not show, whose buy's answer was lost, is bought again
under the same ``custom_id`` once ``order_unconfirmed_minutes`` passed: a second purchase is
impossible, LIS-SKINS refuses a known ``custom_id``. A purchase we hold an id for is never
settled by its absence. Each order gets its own session; one failure never stops the tick.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.config import Settings
from csmarket.core.logging import get_logger
from csmarket.modules.lisskins.api import (
    INFO_MAX_IDS,
    LisskinsBuyClient,
    LisskinsError,
    LisskinsPurchase,
    LisskinsUnavailableError,
    Purchase,
)
from csmarket.modules.orders.lisskins_buying import attempt_lisskins_buy
from csmarket.modules.orders.lisskins_status import apply_report, lock
from csmarket.modules.orders.models import Order
from csmarket.modules.skins.api import TradeClient

log = get_logger("csmarket.orders.lisskins_reconcile")

#: Steam's trade protection (7 days) and a margin: an accepted trade can be rolled back.
PROTECTION = timedelta(days=8)
#: How often a delivered order inside :data:`PROTECTION` is asked about.
PROTECTION_POLL_EVERY = timedelta(minutes=10)
#: Pending buys per tick.
BUY_BATCH = 20

SessionFactory = Callable[[], AsyncSession]


async def _pending(db: AsyncSession) -> list[str]:
    """Orders whose buy is due (the lease decides who takes it)."""
    rows = await db.scalars(
        select(LisskinsPurchase.order_id)
        .join(Order, Order.id == LisskinsPurchase.order_id)
        .where(Order.status == "buying", LisskinsPurchase.buy_pending.is_(True))
        .order_by(Order.created_at)
        .limit(BUY_BATCH)
    )
    return list(rows.all())


async def _to_poll(db: AsyncSession) -> dict[str, str]:
    """``custom_id → order id`` of the purchases to ask about: open ones first, then those
    in trade protection, each longest-unpolled first."""
    at = now()
    open_ = and_(
        Order.status.in_(("buying", "trade_sent")), LisskinsPurchase.buy_pending.is_(False)
    )
    protected = and_(
        Order.status == "delivered",
        LisskinsPurchase.status == "accepted",
        Order.delivered_at > at - PROTECTION,
        or_(
            LisskinsPurchase.last_polled_at.is_(None),
            LisskinsPurchase.last_polled_at <= at - PROTECTION_POLL_EVERY,
        ),
    )
    rows = await db.execute(
        select(LisskinsPurchase.custom_id, LisskinsPurchase.order_id)
        .join(Order, Order.id == LisskinsPurchase.order_id)
        .where(or_(open_, protected))
        .order_by(
            Order.status == "delivered",
            LisskinsPurchase.last_polled_at.asc().nulls_first(),
            Order.created_at,
        )
        .limit(INFO_MAX_IDS)
    )
    return {custom_id: order_id for custom_id, order_id in rows.all()}


def _settle_unseen(order: Order, purchase: LisskinsPurchase, settings: Settings) -> str:
    """LIS-SKINS shows nothing under our ``custom_id``. A lost buy past the wait is due
    again under the same id (spec §6); anything else is left as it is."""
    purchase.last_polled_at = now()
    unseen = purchase.buy_unconfirmed_at
    if unseen is None or purchase.purchase_id is not None or order.status != "buying":
        return "unchanged"
    if now() - unseen < timedelta(minutes=settings.order_unconfirmed_minutes):
        return "unchanged"
    purchase.buy_unconfirmed_at = None
    purchase.buy_pending = True
    order.next_check_at = None  # due for the next tick's buy at once
    log.warning("orders.lisskins.repeat_unseen", number=order.number)
    return "repeat"


async def apply_polled(
    db: AsyncSession,
    *,
    order_id: str,
    custom_id: str,
    report: Purchase | None,
    settings: Settings,
) -> str:
    """Apply one polled answer under the locks; commits.

    ``report`` ``None``: LIS-SKINS holds no purchase under ``custom_id``. A row that went
    pending, or was pointed at a substitute, during the call is left alone.
    """
    pair = await lock(db, order_id)
    if pair is None or pair[1].buy_pending or pair[1].custom_id != custom_id:
        await db.commit()
        return "unchanged"
    order, purchase = pair
    if report is None:
        outcome = _settle_unseen(order, purchase, settings)
    else:
        purchase.buy_unconfirmed_at = None
        outcome = await apply_report(db, order=order, purchase=purchase, report=report)
    await db.commit()
    if outcome != "unchanged":
        log.info("orders.lisskins.polled", number=order.number, outcome=outcome)
    return outcome


async def _poll(
    db_factory: SessionFactory,
    client: LisskinsBuyClient,
    due: dict[str, str],
    *,
    settings: Settings,
) -> None:
    try:
        reports = await client.info(custom_ids=list(due))
    except (LisskinsError, LisskinsUnavailableError) as exc:
        log.warning("orders.lisskins.info_failed", error=type(exc).__name__)
        return
    found = {p.custom_id: p for p in reports if p.custom_id is not None}
    for custom_id, order_id in due.items():
        try:
            async with db_factory() as db:
                await apply_polled(
                    db,
                    order_id=order_id,
                    custom_id=custom_id,
                    report=found.get(custom_id),
                    settings=settings,
                )
        except Exception as exc:  # noqa: BLE001 -- one order must not stop the tick
            log.error("orders.lisskins.poll_failed", error=type(exc).__name__)  # noqa: TRY400


async def reconcile_lisskins(
    db_factory: SessionFactory,
    client: LisskinsBuyClient,
    *,
    settings: Settings,
    waxpeer: TradeClient | None = None,
) -> int:
    """One tick: buy the due buys, then poll everything else in one call.

    Returns:
        How many orders the tick looked at.
    """
    async with db_factory() as db:
        pending = await _pending(db)
        due = await _to_poll(db)
        await db.commit()
    for order_id in pending:
        try:
            async with db_factory() as db:
                await attempt_lisskins_buy(
                    db, client, order_id=order_id, settings=settings, waxpeer=waxpeer
                )
        except Exception as exc:  # noqa: BLE001 -- one order must not stop the tick
            log.error("orders.lisskins.reconcile_failed", error=type(exc).__name__)  # noqa: TRY400
    if due:
        await _poll(db_factory, client, due, settings=settings)
    return len(pending) + len(due)


__all__ = [
    "BUY_BATCH",
    "PROTECTION",
    "PROTECTION_POLL_EVERY",
    "apply_polled",
    "reconcile_lisskins",
]
```

- [ ] **Step 4: Write the scheduler job**

```python
# apps/scheduler/src/csmarket_scheduler/jobs/lisskins_reconcile.py
"""Every 30 s: buy pending LIS-SKINS orders and poll the rest in one ``market/info`` call
(``orders.lisskins_reconcile``; spec 2026-10-07 §6 — there is no webhook).

Skipped without an API key; runs with the switch off too, so open orders still settle.
``max_instances=1`` and ``coalesce=True``. A failure is logged by type only.
"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from csmarket.core.config import get_settings
from csmarket.core.db import get_session_factory
from csmarket.core.logging import get_logger
from csmarket.modules.lisskins.api import client_for
from csmarket.modules.orders.api import reconcile_lisskins
from csmarket.modules.skins.api import trade_client

from csmarket_scheduler.startup import first_run_after

log = get_logger("csmarket.scheduler.lisskins_reconcile")

JOB_ID = "lisskins.reconcile"
INTERVAL_SECONDS = 30


async def run() -> None:
    """One tick. Never raises."""
    settings = get_settings()
    # The key, not the switch: orders paid before a switch-off are followed to the end.
    if not settings.lisskins_api_key:
        return
    try:
        looked = await reconcile_lisskins(
            get_session_factory(),
            client_for(settings, timeout_seconds=settings.lisskins_buy_timeout_seconds),
            settings=settings,
            waxpeer=trade_client(settings),
        )
    except Exception as exc:  # noqa: BLE001 -- a tick never raises; the next one retries
        log.warning("lisskins.reconcile.failed", error=type(exc).__name__)
        return
    if looked:
        log.info("lisskins.reconcile.tick", orders=looked)


def register(scheduler: AsyncIOScheduler) -> None:
    """Every :data:`INTERVAL_SECONDS`; first run 340 s after start."""
    scheduler.add_job(
        run,
        trigger="interval",
        seconds=INTERVAL_SECONDS,
        id=JOB_ID,
        next_run_time=first_run_after(340),
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    log.info("scheduler.job.registered", job=JOB_ID, interval_seconds=INTERVAL_SECONDS)
```

Register it in `main.py` after `lisskins_snapshot.register(scheduler)`; `test_main.py` lists `"lisskins.reconcile"` after `"lisskins.snapshot"`.

- [ ] **Step 5: Run tests and gates**

Run: `cd apps/api && uv run pytest tests/integration/test_lisskins_reconcile.py tests/integration/test_orders_lisskins_buying.py -q && cd ../scheduler && uv run pytest tests -q && cd ../.. && make lint typecheck`
Expected: PASS; clean.

- [ ] **Step 6: Commit**

```bash
git add apps/api/src apps/api/tests apps/scheduler
git commit -m "feat(api/orders): poll LIS-SKINS purchases in one call per tick; lost buys settled by custom id; rollbacks seen through trade protection" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: Balance, admin order page and dashboard, metrics, alerts

**Files:**

- Create: `apps/api/src/csmarket/modules/lisskins/balance.py`, `apps/scheduler/src/csmarket_scheduler/jobs/lisskins_balance.py`
- Modify: `apps/api/src/csmarket/core/metrics.py` (balance gauges, enabled gauge)
- Modify: `apps/api/src/csmarket/modules/orders/dashboard.py` (`LisskinsBalance`, `Dashboard.lisskins`), `apps/api/src/csmarket/modules/admin/dashboard_schemas.py` (`LisskinsOut`, `DashboardOut.lisskins`)
- Modify: `apps/api/src/csmarket/modules/admin/orders_schemas.py:113,196-230` (`source` gains `lisskins`; `AdminLisskinsPurchaseOut`; `AdminOrderDetail.lisskins`)
- Modify: `apps/api/src/csmarket/modules/admin/orders_service.py:209-300` (load the purchase by source; `_spent` reads either purchase)
- Modify: `apps/api/src/csmarket/modules/orders/api.py` (export `purchase_of`, `PurchaseRow`)
- Modify: `infra/prometheus/alerts/orders.yml` (three alerts), `apps/scheduler/src/csmarket_scheduler/main.py`, `apps/scheduler/tests/test_main.py`
- Modify: `docs/architecture/metrics.md`, `docs/architecture/cache-keys.md`
- Test: `apps/api/tests/integration/test_lisskins_balance.py`, additions to `test_admin_orders.py` and `test_admin_dashboard.py`, `apps/scheduler/tests/test_lisskins_balance.py`

**Interfaces:**

- Produces in `lisskins/balance.py`: `BALANCE_KEY = "lisskins:balance"`; `async refresh_balance(redis, client: BalanceClient, *, settings) -> Balance | None`; `async cached_balance(redis) -> tuple[Decimal | None, Decimal | None, datetime | None]` (`available`, `locked`, `read_at`), re-exported by `api.py` as `lisskins_cached_balance`.
- Produces in `core/metrics.py`: gauges `csmarket_lisskins_balance_available_usd`, `csmarket_lisskins_balance_locked_usd`, `csmarket_lisskins_balance_threshold_usd`, `csmarket_lisskins_balance_read_timestamp_seconds`, `csmarket_lisskins_enabled`; `set_lisskins_balance(available_usd: float, locked_usd: float, threshold_usd: float) -> None`, `set_lisskins_enabled(*, enabled: bool) -> None`.
- Produces in the API: `GET /admin/dashboard` → `lisskins: {available_usd, locked_usd, read_at}`; `GET /admin/orders/{number}` → `order.source` may be `lisskins`, `lisskins: AdminLisskinsPurchaseOut | null` with `custom_id, skin_id, purchase_id, status, return_reason, error, offer_id, offer_url, offer_expiry_at, amount_usd, buy_pending, buy_unconfirmed_at, attention_reason, resolved_at`.

- [ ] **Step 1: Write the failing tests**

```python
# apps/api/tests/integration/test_lisskins_balance.py
"""The LIS-SKINS balance: cached for the dashboard, exported as gauges; a failed read keeps
the last good copy."""

from __future__ import annotations

from decimal import Decimal

from csmarket.core.config import get_settings
from csmarket.core.redis import get_redis
from csmarket.modules.lisskins.api import Balance, LisskinsUnavailableError
from csmarket.modules.lisskins.balance import cached_balance, refresh_balance
from prometheus_client import REGISTRY


class _Client:
    def __init__(self, answer: Balance | Exception) -> None:
        self.answer = answer

    async def balance(self) -> Balance:
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


async def test_unknown_before_any_read() -> None:
    assert await cached_balance(get_redis()) == (None, None, None)


async def test_refresh_caches_and_exports() -> None:
    settings = get_settings().model_copy(update={"lisskins_balance_alert_usd": Decimal(50)})
    answer = Balance(available=Decimal("99.96"), locked=Decimal("1.5"), protected=Decimal(0))
    assert await refresh_balance(get_redis(), _Client(answer), settings=settings) == answer
    available, locked, read_at = await cached_balance(get_redis())
    assert (available, locked) == (Decimal("99.96"), Decimal("1.5")) and read_at is not None
    assert REGISTRY.get_sample_value("csmarket_lisskins_balance_available_usd") == 99.96
    assert REGISTRY.get_sample_value("csmarket_lisskins_balance_threshold_usd") == 50.0


async def test_a_failed_read_keeps_the_cache() -> None:
    settings = get_settings()
    one = Balance(available=Decimal(1), locked=Decimal(0), protected=Decimal(0))
    await refresh_balance(get_redis(), _Client(one), settings=settings)
    assert await refresh_balance(get_redis(), _Client(LisskinsUnavailableError("x")), settings=settings) is None
    assert (await cached_balance(get_redis()))[0] == Decimal(1)
```

In `test_admin_orders.py` add (import `make_lisskins_order`, `OFFER`):

```python
async def test_a_lisskins_orders_page_names_its_source_and_shows_its_purchase(
    integration_client: AsyncClient, admin_headers: Headers, db_session: AsyncSession
) -> None:
    order, _ = await make_lisskins_order(db_session, amount_units=12_340)
    r = await integration_client.get(f"/api/v1/admin/orders/{order.number}", headers=await admin_headers())
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["order"]["source"], body["order"]["offer_id"], body["order"]["listing_id"]) == (
        "lisskins",
        "ls:125345",
        None,
    )
    assert body["trade"] is None and body["skinslink"] is None
    ls = body["lisskins"]
    assert (ls["custom_id"], ls["skin_id"], ls["purchase_id"], ls["status"]) == (order.id, 125345, 55, "wait_accept")
    assert ls["offer_url"] == f"https://steamcommunity.com/tradeoffer/{OFFER}/"
    assert ls["amount_usd"] == "12.340000"
```

(Use the file's existing names for the admin-headers fixture and type alias; read its top first.) In `test_admin_dashboard.py`, `test_in_flight_attention_and_no_cached_balance` adds `assert body["lisskins"] == {"available_usd": None, "locked_usd": None, "read_at": None}`.

```python
# apps/scheduler/tests/test_lisskins_balance.py
"""``lisskins.balance``: exports whether LIS-SKINS is on every tick; reads the balance only
while it is; never raises; every 5 minutes."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from csmarket.core.config import get_settings
from csmarket_scheduler.jobs import lisskins_balance as job
from prometheus_client import REGISTRY

ACTIVE = {"lisskins_enabled": True, "lisskins_api_key": "k"}


def _settings(monkeypatch: pytest.MonkeyPatch, *, active: bool) -> None:
    s = get_settings().model_copy(update=ACTIVE if active else {})
    monkeypatch.setattr(job, "get_settings", lambda: s)


async def test_inactive_exports_off_and_reads_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    read = AsyncMock()
    monkeypatch.setattr(job, "refresh_balance", read)
    _settings(monkeypatch, active=False)
    await job.run()
    read.assert_not_awaited()
    assert REGISTRY.get_sample_value("csmarket_lisskins_enabled") == 0


async def test_active_exports_on_and_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    read = AsyncMock(return_value=None)
    monkeypatch.setattr(job, "refresh_balance", read)
    _settings(monkeypatch, active=True)
    await job.run()
    read.assert_awaited_once()
    assert REGISTRY.get_sample_value("csmarket_lisskins_enabled") == 1


async def test_a_failure_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(job, "refresh_balance", AsyncMock(side_effect=RuntimeError("boom")))
    _settings(monkeypatch, active=True)
    await job.run()


def test_registers_every_5_minutes() -> None:
    scheduler = AsyncIOScheduler()
    job.register(scheduler)
    registered = scheduler.get_job(job.JOB_ID)
    assert registered is not None and registered.trigger.interval.total_seconds() == 300
```

- [ ] **Step 2: Run them**

Run: `cd apps/api && uv run pytest tests/integration/test_lisskins_balance.py tests/integration/test_admin_orders.py tests/integration/test_admin_dashboard.py -q; cd ../scheduler && uv run pytest tests/test_lisskins_balance.py -q`
Expected: FAIL — `ModuleNotFoundError: lisskins.balance`; no `lisskins` in the admin answers.

- [ ] **Step 3: Implement**

`core/metrics.py`, beside the Skinslink balance gauges:

```python
LISSKINS_BALANCE_AVAILABLE_USD = Gauge(
    "csmarket_lisskins_balance_available_usd",
    "The LIS-SKINS balance free to spend, USD (alert: LisskinsBalanceLow).",
)
LISSKINS_BALANCE_LOCKED_USD = Gauge(
    "csmarket_lisskins_balance_locked_usd", "The LIS-SKINS balance locked by open purchases, USD."
)
LISSKINS_BALANCE_THRESHOLD_USD = Gauge(
    "csmarket_lisskins_balance_threshold_usd",
    "The balance below which LisskinsBalanceLow fires (setting lisskins_balance_alert_usd).",
)
LISSKINS_BALANCE_READ_TIMESTAMP = Gauge(
    "csmarket_lisskins_balance_read_timestamp_seconds",
    "Unix time of the last successful LIS-SKINS balance read.",
)
LISSKINS_ENABLED = Gauge(
    "csmarket_lisskins_enabled",
    "1 while LIS-SKINS is switched on and keyed, else 0 (gates the LIS-SKINS alerts).",
)


def set_lisskins_balance(available_usd: float, locked_usd: float, threshold_usd: float) -> None:
    """Export a successful LIS-SKINS balance read and the alert threshold. Never raises."""
    try:
        LISSKINS_BALANCE_AVAILABLE_USD.set(available_usd)
        LISSKINS_BALANCE_LOCKED_USD.set(locked_usd)
        LISSKINS_BALANCE_THRESHOLD_USD.set(threshold_usd)
        LISSKINS_BALANCE_READ_TIMESTAMP.set(time.time())
    except Exception as exc:  # noqa: BLE001 -- Rule 2 in the module docstring
        log.warning("metrics.set_failed", metric="csmarket_lisskins_balance", error=type(exc).__name__)


def set_lisskins_enabled(*, enabled: bool) -> None:
    """Whether LIS-SKINS is on (``csmarket_lisskins_enabled``). Never raises."""
    try:
        LISSKINS_ENABLED.set(1 if enabled else 0)
    except Exception as exc:  # noqa: BLE001 -- Rule 2 in the module docstring
        log.warning("metrics.set_failed", metric="csmarket_lisskins_enabled", error=type(exc).__name__)
```

(`__all__` gains `set_lisskins_balance`, `set_lisskins_enabled`, `set_lisskins_snapshot`.)

`lisskins/balance.py`:

```python
"""The LIS-SKINS balance (spec 2026-10-07 §7): read every 5 minutes by the
``lisskins.balance`` job, cached for the admin dashboard and exported as gauges
(``LisskinsBalanceLow``). A failed read keeps the last good copy and stamp."""

from __future__ import annotations

import contextlib
import json
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Protocol

from redis.asyncio import Redis
from redis.exceptions import RedisError

from csmarket.core.clock import now
from csmarket.core.config import Settings
from csmarket.core.logging import get_logger
from csmarket.core.metrics import set_lisskins_balance
from csmarket.modules.lisskins.client import Balance, LisskinsError, LisskinsUnavailableError

log = get_logger("csmarket.lisskins.balance")

#: The last good balance read (``docs/architecture/cache-keys.md``).
BALANCE_KEY = "lisskins:balance"
_TTL_SECONDS = 3600


class BalanceClient(Protocol):
    """What the balance read needs from LIS-SKINS."""

    async def balance(self) -> Balance:
        """``GET /user/balance``."""
        ...


async def refresh_balance(redis: Redis, client: BalanceClient, *, settings: Settings) -> Balance | None:
    """Read the balance, cache it and export it; ``None`` (nothing changed) on a failure."""
    try:
        answer = await client.balance()
    except (LisskinsError, LisskinsUnavailableError) as exc:
        log.warning("lisskins.balance.failed", error=type(exc).__name__)
        return None
    set_lisskins_balance(
        float(answer.available), float(answer.locked), float(settings.lisskins_balance_alert_usd)
    )
    try:
        value = {
            "available": str(answer.available),
            "locked": str(answer.locked),
            "read_at": now().isoformat(),
        }
        await redis.set(BALANCE_KEY, json.dumps(value), ex=_TTL_SECONDS)
    except RedisError as exc:
        log.warning("lisskins.balance.cache_failed", error=type(exc).__name__)
    return answer


async def cached_balance(redis: Redis) -> tuple[Decimal | None, Decimal | None, datetime | None]:
    """``(available, locked, read_at)`` of the last good read; all ``None`` when unknown."""
    with contextlib.suppress(RedisError, ValueError, KeyError, TypeError, InvalidOperation):
        raw = await redis.get(BALANCE_KEY)
        if raw is not None:
            data = json.loads(raw)
            return (
                Decimal(data["available"]),
                Decimal(data["locked"]),
                datetime.fromisoformat(data["read_at"]),
            )
    return None, None, None


__all__ = ["BALANCE_KEY", "BalanceClient", "cached_balance", "refresh_balance"]
```

`jobs/lisskins_balance.py` — the Skinslink balance job with `lisskins` names: `JOB_ID = "lisskins.balance"`, `INTERVAL_SECONDS = 300`, `set_lisskins_enabled(enabled=settings.lisskins_active)` first, return unless active, `await refresh_balance(get_redis(), client_for(settings), settings=settings)` in a `try` that logs `lisskins.balance.tick_failed` by type, `first_run_after(360)`. Register in `main.py` after `lisskins_reconcile`; `test_main.py` lists `"lisskins.balance"` after `"lisskins.reconcile"`.

`orders/dashboard.py`:

```python
class LisskinsBalance(_Frozen):
    available_usd: Decimal | None
    locked_usd: Decimal | None
    read_at: datetime | None
```

`Dashboard.lisskins: LisskinsBalance`; in `summary`: `ls_available, ls_locked, ls_read_at = await lisskins_cached_balance(redis)` and `lisskins=LisskinsBalance(available_usd=ls_available, locked_usd=ls_locked, read_at=ls_read_at)`. `admin/dashboard_schemas.py`:

```python
class LisskinsOut(BaseModel):
    #: The last good read by the balance job; ``null`` when unknown (none in the last hour).
    available_usd: str | None
    locked_usd: str | None
    read_at: datetime | None
```

`DashboardOut.lisskins: LisskinsOut`, filled in `of()` like `skinslink` (`_money` on each non-`None` amount).

`admin/orders_schemas.py`: `source: Literal["waxpeer", "skinslink", "lisskins"]` (comment: "`listing_id` is `None` for a Skinslink or LIS-SKINS order"), and:

```python
class AdminLisskinsPurchaseOut(BaseModel):
    """A LIS-SKINS order's purchase as the operator needs it (spec 2026-10-07 §7)."""

    #: Our idempotency key at LIS-SKINS — what its purchase history is searched by.
    custom_id: str
    #: The LIS-SKINS lot bought.
    skin_id: int
    purchase_id: int | None
    #: The skin's status word (``processing`` … ``return``).
    status: str | None
    return_reason: str | None
    error: str | None
    #: Steam's trade offer id.
    offer_id: str | None
    offer_url: str | None
    offer_expiry_at: datetime | None
    #: What LIS-SKINS charged, USD with six places.
    amount_usd: str | None
    buy_pending: bool
    buy_unconfirmed_at: datetime | None
    attention_reason: AttentionReason | None
    resolved_at: datetime | None
```

and `AdminOrderDetail.lisskins: AdminLisskinsPurchaseOut | None = None` (comment "A LIS-SKINS order's purchase; `None` otherwise"); `__all__` adds it.

`admin/orders_service.py` (imports `PurchaseRow`, `purchase_of` from `orders.api`, `LisskinsPurchase` from `lisskins.api`):

```python
def _spent(order: Order, trade: SkinTrade | None, purchase: PurchaseRow | None) -> Decimal:
    """What the market charged, USD; the agreed cost until it says."""
    if trade is not None and trade.bought_units is not None:
        return Decimal(trade.bought_units) / 1000
    if purchase is not None and purchase.amount_units is not None:
        return Decimal(purchase.amount_units) / 1000
    return order.cost_usd


def _lisskins_out(p: LisskinsPurchase) -> AdminLisskinsPurchaseOut:
    offer = p.steam_trade_offer_id
    return AdminLisskinsPurchaseOut.model_validate(
        {
            "custom_id": p.custom_id,
            "skin_id": p.skin_id,
            "purchase_id": p.purchase_id,
            "status": p.status,
            "return_reason": p.return_reason,
            "error": p.error,
            "offer_id": offer,
            "offer_url": f"https://steamcommunity.com/tradeoffer/{offer}/" if offer else None,
            "offer_expiry_at": p.offer_expiry_at,
            "amount_usd": None if p.amount_units is None else _usd(Decimal(p.amount_units) / 1000),
            "buy_pending": p.buy_pending,
            "buy_unconfirmed_at": p.buy_unconfirmed_at,
            "attention_reason": p.attention_reason,
            "resolved_at": p.resolved_at,
        }
    )
```

`_order_full`'s `purchase` parameter becomes `PurchaseRow | None`; in `order_detail` replace the Skinslink-only lookup with `purchase = await purchase_of(db, order, lock=False)` and build `skinslink=_purchase_out(purchase) if isinstance(purchase, SkinslinkPurchase) else None, lisskins=_lisskins_out(purchase) if isinstance(purchase, LisskinsPurchase) else None`.

`infra/prometheus/alerts/orders.yml`, after the Skinslink block:

```yaml
# --- LIS-SKINS, the third buy source (spec 2026-10-07). Gated by
# csmarket_lisskins_enabled (the scheduler's balance job sets it every 5 minutes).

# The applied export is over 20 minutes old: LIS-SKINS lots and prices are hidden (a
# stale snapshot sells nothing) until a fresh export is applied.
- alert: LisskinsSnapshotStale
  expr: >
    (time() - max(csmarket_lisskins_snapshot_timestamp_seconds{job="scheduler"}) > 1200)
    and on() (max(csmarket_lisskins_enabled{job="scheduler"}) == 1)
  for: 5m
  labels: { severity: warn }
  annotations:
    summary: "The LIS-SKINS snapshot is over 20 minutes old"
    description: >
      LIS-SKINS lots are off the storefront until a fresh export is applied. Check the
      scheduler's lisskins.snapshot log lines and whether the export URL answers.
    runbook: "https://github.com/jamaomonov/csmarket/blob/main/docs/runbooks/lisskins.md#snapshot-stale"

- alert: LisskinsBalanceLow
  expr: >
    (min(csmarket_lisskins_balance_available_usd{job="scheduler"})
      < min(csmarket_lisskins_balance_threshold_usd{job="scheduler"}))
    and on() (max(csmarket_lisskins_enabled{job="scheduler"}) == 1)
  for: 10m
  labels: { severity: page }
  annotations:
    summary: 'LIS-SKINS balance ${{ $value | printf "%.2f" }}, below the alert threshold'
    description: >
      Top up the LIS-SKINS balance before its purchases start failing and refunding
      customers.
    runbook: "https://github.com/jamaomonov/csmarket/blob/main/docs/runbooks/lisskins.md#balance-low"

# Purchases refused, forbidden or unanswered: several in 15 minutes means the key, the
# IP, the balance or LIS-SKINS itself, not one sold lot.
- alert: LisskinsBuyFailures
  expr: >
    sum(increase(csmarket_lisskins_calls_total{endpoint="buy",outcome=~"refused|forbidden|unavailable"}[15m])) > 5
  labels: { severity: warn }
  annotations:
    summary: "LIS-SKINS purchases keep failing"
    description: >
      More than five LIS-SKINS purchases were refused, forbidden or unanswered in 15
      minutes. Check the worker's orders.lisskins_buy lines and LIS-SKINS' status.
    runbook: "https://github.com/jamaomonov/csmarket/blob/main/docs/runbooks/lisskins.md#buy-failures"
```

`docs/architecture/metrics.md`: the counter `csmarket_lisskins_calls_total{endpoint,outcome}` (closed sets from Task 2), `csmarket_lisskins_snapshot_timestamp_seconds`, the four balance gauges and `csmarket_lisskins_enabled`, each with its writer and alert. `docs/architecture/cache-keys.md`: rows `lisskins:balance` (3600 s; the `lisskins.balance` job; `GET /admin/dashboard`; `{available, locked, read_at}`), `lisskins:check:budget:<YYYYmmddHHMM>` (120 s; checkout; the 100-calls-a-minute budget), `lisskins:check:breaker` (120 s; set on a check outage; checkout skips the call while it exists).

- [ ] **Step 4: Run tests and gates**

Run: `cd apps/api && uv run pytest tests/integration/test_lisskins_balance.py tests/integration/test_admin_orders.py tests/integration/test_admin_dashboard.py -q && cd ../scheduler && uv run pytest tests -q && cd ../.. && make lint typecheck && make gen-api && docker run --rm -v "$PWD/infra/prometheus:/p:ro" --entrypoint promtool prom/prometheus:v3.12.0 check rules /p/alerts/orders.yml`
Expected: PASS; clean; `docs/api/openapi.json` and `packages/api-client` regenerated (the two admin schemas changed); rules valid.

- [ ] **Step 5: Commit**

```bash
git add apps docs/api packages/api-client docs/architecture infra/prometheus/alerts/orders.yml
git commit -m "feat(api/lisskins): balance read, admin order page and dashboard, metrics and alerts" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12: Admin SPA and storefront

Decision: «Разобрано» in the admin read the Waxpeer trade only, so a Skinslink attention could not be resolved from the page either; it now reads the order's trade, Skinslink purchase or LIS-SKINS purchase.

**Files:**

- Modify: `apps/admin/src/features/orders/api.ts` (`source`, `AdminLisskinsPurchaseOut`, `AdminOrderDetail.lisskins`), `fixtures.ts` (`lisskins: null` on `DETAIL`; a `LISSKINS` fixture)
- Create: `apps/admin/src/features/orders/LisskinsBlock.tsx`
- Modify: `apps/admin/src/features/orders/OrderDetail.tsx` (`SOURCE_LABELS`, the purchase block), `OrderActions.tsx:108-111` (`needsResolve`)
- Modify: `apps/admin/src/features/dashboard/api.ts`, `DashboardPage.tsx` (the LIS-SKINS tile), `DashboardPage.test.tsx`
- Test: `apps/admin/src/features/orders/OrderDetail.test.tsx`, `apps/admin/src/features/dashboard/DashboardPage.test.tsx`, `apps/web/src/lib/orders.test.ts`

**Interfaces:**

- Consumes: the admin API of Task 11 (`lisskins` on the order page and the dashboard). The storefront needs no code change: offer ids are already opaque strings end to end; its test pins that an `ls:` id passes through.

- [ ] **Step 1: Write the failing tests**

In `OrderDetail.test.tsx` (import `LISSKINS` from `./fixtures`):

```tsx
it("names a LIS-SKINS order's source and shows its purchase", async () => {
  api.getOrder.mockResolvedValue({
    ...DETAIL,
    order: { ...DETAIL.order, source: "lisskins", offer_id: "ls:125345", listing_id: null },
    trade: null,
    lisskins: LISSKINS,
  });
  renderDetail();
  const order = await screen.findByRole("region", { name: "Заказ" });
  expect(within(order).getByText("LIS-SKINS · ls:125345")).toBeInTheDocument();
  const purchase = screen.getByRole("region", { name: "Покупка LIS-SKINS" });
  expect(within(purchase).getByText("55")).toBeInTheDocument();
  expect(within(purchase).getByText("wait_accept")).toBeInTheDocument();
  expect(within(purchase).getByText("$12.340000")).toBeInTheDocument();
  expect(within(purchase).getByRole("link", { name: "7252638866" })).toHaveAttribute(
    "href",
    "https://steamcommunity.com/tradeoffer/7252638866/",
  );
  expect(within(purchase).getByText("откат после получения")).toBeInTheDocument();
  expect(screen.queryByRole("region", { name: "Обмен" })).toBeNull();
});

it("offers «Разобрано» for a purchase's open attention", async () => {
  api.getOrder.mockResolvedValue({
    ...DETAIL,
    order: { ...DETAIL.order, source: "lisskins", offer_id: "ls:125345", listing_id: null },
    trade: null,
    lisskins: LISSKINS,
    can_refund: false,
    can_retry: false,
  });
  renderDetail();
  expect(await screen.findByRole("button", { name: "Разобрано" })).toBeInTheDocument();
});
```

`fixtures.ts`:

```ts
export const LISSKINS: AdminLisskinsPurchaseOut = {
  custom_id: "6f1c2a52-0000-4000-8000-000000000001",
  skin_id: 125345,
  purchase_id: 55,
  status: "wait_accept",
  return_reason: null,
  error: null,
  offer_id: "7252638866",
  offer_url: "https://steamcommunity.com/tradeoffer/7252638866/",
  offer_expiry_at: "2026-10-07T19:50:35Z",
  amount_usd: "12.340000",
  buy_pending: false,
  buy_unconfirmed_at: null,
  attention_reason: "rolled_back",
  resolved_at: null,
};
```

In `DashboardPage.test.tsx`, `DATA` gains `lisskins: { available_usd: "99.96", locked_usd: "1.5", read_at: new Date(Date.now() - 3 * 60_000).toISOString() }` and:

```tsx
expect(tile("Баланс LIS-SKINS")).toHaveTextContent("$99.96");
expect(tile("Баланс LIS-SKINS")).toHaveTextContent("заблокировано $1.5");
expect(tile("Баланс LIS-SKINS")).toHaveTextContent("обновлено 3 мин назад");
```

plus a case `"an unknown LIS-SKINS balance says so"` mirroring the Skinslink one with `lisskins: { available_usd: null, locked_usd: null, read_at: null }` → `"неизвестно"`.

In `apps/web/src/lib/orders.test.ts`, inside `"a gone offer carries the next one, or null"`:

```ts
const lis = await createError(
  conflict({ code: "offer_gone", next_offer: { listing_id: "ls:125345", price_uzs: "171800" } }),
);
expect((lis as OfferGoneError).nextOffer).toEqual({
  listing_id: "ls:125345",
  price_uzs: "171800",
});
```

- [ ] **Step 2: Run them**

Run: `pnpm --filter @csmarket/admin exec vitest run src/features/orders src/features/dashboard && pnpm --filter @csmarket/web exec vitest run src/lib/orders.test.ts`
Expected: admin FAIL (types and the region missing); the web test PASSES already (ids are opaque) — it is a pin.

- [ ] **Step 3: Implement**

`orders/api.ts`: `source: "waxpeer" | "skinslink" | "lisskins";` and

```ts
/** A LIS-SKINS order's purchase (spec 2026-10-07). */
export interface AdminLisskinsPurchaseOut {
  /** Our idempotency key at LIS-SKINS — what its purchase history is searched by. */
  custom_id: string;
  skin_id: number;
  purchase_id: number | null;
  status: string | null;
  return_reason: string | null;
  error: string | null;
  offer_id: string | null;
  offer_url: string | null;
  offer_expiry_at: string | null;
  /** USD with six places. */
  amount_usd: string | null;
  buy_pending: boolean;
  buy_unconfirmed_at: string | null;
  attention_reason: AttentionReason | null;
  resolved_at: string | null;
}
```

and in `AdminOrderDetail`: `/** `null` unless a LIS-SKINS order. */ lisskins: AdminLisskinsPurchaseOut | null;`. `DETAIL` in `fixtures.ts` gains `lisskins: null`.

`LisskinsBlock.tsx`:

```tsx
/** «Покупка LIS-SKINS»: a LIS-SKINS order's purchase — status, Steam offer, ids to search by. */
import { type ReactNode } from "react";

import { type AdminLisskinsPurchaseOut } from "./api";
import { ATTENTION_LABELS } from "./labels";

import { formatDateTime } from "@/lib/format";

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex gap-3">
      <dt className="text-fg-muted w-40 shrink-0">{label}</dt>
      <dd className="min-w-0 break-all">{children}</dd>
    </div>
  );
}

function when(iso: string | null): string {
  return iso === null ? "—" : formatDateTime(iso);
}

interface LisskinsBlockProps {
  purchase: AdminLisskinsPurchaseOut;
}

export function LisskinsBlock({ purchase: p }: LisskinsBlockProps) {
  return (
    <section aria-label="Покупка LIS-SKINS" className="space-y-2">
      <h2 className="text-lg font-semibold">Покупка LIS-SKINS</h2>
      <dl className="space-y-1 text-sm">
        <Field label="Purchase id">{p.purchase_id ?? "—"}</Field>
        <Field label="custom_id">{p.custom_id}</Field>
        <Field label="Лот">{p.skin_id}</Field>
        <Field label="Статус">{p.status ?? "—"}</Field>
        <Field label="Предложение">
          {p.offer_url !== null && p.offer_id !== null ? (
            <a href={p.offer_url} target="_blank" rel="noreferrer" className="text-accent">
              {p.offer_id}
            </a>
          ) : (
            "—"
          )}
        </Field>
        {p.offer_expiry_at !== null && <Field label="Принять до">{when(p.offer_expiry_at)}</Field>}
        <Field label="Списано">{p.amount_usd === null ? "—" : `$${p.amount_usd}`}</Field>
        {p.return_reason !== null && (
          <Field label="Возврат">
            {p.error === null ? p.return_reason : `${p.return_reason} · ${p.error}`}
          </Field>
        )}
        {p.buy_pending && <Field label="Покупка">ждёт попытки</Field>}
        {p.buy_unconfirmed_at !== null && (
          <Field label="Ответ потерян">{when(p.buy_unconfirmed_at)}</Field>
        )}
        {p.attention_reason !== null && (
          <Field label="Внимание">
            {ATTENTION_LABELS[p.attention_reason]}
            {p.resolved_at !== null && ` · разобрано ${when(p.resolved_at)}`}
          </Field>
        )}
      </dl>
    </section>
  );
}
```

`OrderDetail.tsx`: `SOURCE_LABELS` gains `lisskins: "LIS-SKINS"`; replace the Skinslink-or-trade ternary with a component:

```tsx
interface BoughtProps {
  detail: AdminOrderDetail;
}

/** The market's side of the order: a purchase block, or the Waxpeer trade. */
function Bought({ detail }: BoughtProps) {
  if (detail.skinslink !== null) return <SkinslinkBlock purchase={detail.skinslink} />;
  if (detail.lisskins !== null) return <LisskinsBlock purchase={detail.lisskins} />;
  return <TradeBlock trade={detail.trade} />;
}
```

used as `<Bought detail={detail} />`. `OrderActions.tsx`:

```tsx
// A Skinslink or LIS-SKINS order keeps its attention on its purchase.
const watched = trade ?? detail.skinslink ?? detail.lisskins;
const needsResolve =
  watched !== null && watched.attention_reason !== null && watched.resolved_at === null;
```

`dashboard/api.ts`: `lisskins: { available_usd: string | null; locked_usd: string | null; read_at: string | null };`. `DashboardPage.tsx` (docstring: "the Waxpeer, Skinslink and LIS-SKINS balances"), after the Skinslink tile:

```tsx
<Tile title="Баланс LIS-SKINS">
  {lisskins.available_usd === null || lisskins.read_at === null ? (
    <span>неизвестно</span>
  ) : (
    <>
      <span>${lisskins.available_usd}</span>
      <span className="text-fg-muted text-sm">заблокировано ${lisskins.locked_usd ?? "0"}</span>
      <span className="text-fg-muted text-sm">{freshness(lisskins.read_at)}</span>
    </>
  )}
</Tile>
```

(destructure `lisskins` beside `skinslink`.)

- [ ] **Step 4: Run gates**

Run: `make lint typecheck && make test-ts`
Expected: clean; all green.

- [ ] **Step 5: Commit**

```bash
git add apps/admin apps/web/src/lib/orders.test.ts
git commit -m "feat(admin/orders): LIS-SKINS purchase block, source label and balance tile; «Разобрано» on any source's attention" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 13: Documents

**Files:**

- Create: `docs/decisions/0012-lisskins-buy-source.md` (from `0000-template.md`), `docs/runbooks/lisskins.md`, `docs/architecture/sequence-diagrams/lisskins-buy.mmd`
- Modify: `apps/api/src/csmarket/modules/lisskins/README.md` (full), `apps/api/src/csmarket/modules/orders/README.md`, `apps/api/src/csmarket/modules/skins/README.md`, `apps/api/src/csmarket/modules/skinslink/README.md` (the scanner moved to `core`; the prices job is `sources.prices`)
- Modify: `docs/architecture/module-map.md`, `docs/security/pii-handling.md`, `docs/api/README.md`, `docs/decisions/0010-skinslink-buy-source.md` (an "Update 2026-10-07" line), `docs/runbooks/skinslink.md` (`skinslink.prices` → `sources.prices`), `docs/tech-debt.md`, `AGENTS.md` (§0, §11)

- [ ] **Step 1: ADR-0012**

Context: on 2026-10-07 LIS-SKINS' instant lots were cheaper than our Skinslink cost on 59 % of the 16 978 names both sell (median −1.7 %) and it sells ~8 500 names we do not (spec "Why"). Decision: LIS-SKINS beside Skinslink as a third `source`; instant (`delivery_type=1`), unlocked lots only; a 5-minute snapshot of the public export (top 10 per item) instead of a live mirror; statuses polled every 30 s in one `market/info` call (no webhook or WebSocket); one shared substitute rule; **the checkout carve-out**: `POST /orders` asks `GET /market/check-availability` once for a chosen `ls:` lot — 4 s timeout, 100 calls/min for the API, a 120 s breaker, a failure accepts the snapshot price (the worker's `max_price` guards). Consequences: a third balance to fund and watch; the export is ~855 MB every 5 minutes (CPU and bandwidth on the VPS); the scanner moved to `core`; rollbacks are watched for 8 days after delivery. Alternatives: the WebSocket feeds (rejected: a long-lived connection and a second state machine for a 30 s gain), slow delivery (dearer, up to 12 h), locked lots (withdraw/return flow).

- [ ] **Step 2: Runbook `docs/runbooks/lisskins.md`**

Sections (each heading is an alert anchor or an operator task): "What we call" (the five endpoints and the export, rate limits); "Credentials" (`CSMARKET_LISSKINS_API_KEY` in `secrets/api.env`, rotation, never in chat; the key answers only from `57.131.198.69`); "Enabling" (`CSMARKET_LISSKINS_ENABLED=true` → `IMAGE_TAG=<tag> docker compose -f docker-compose.prod.yml up -d api worker scheduler`; first snapshot after ~5–9 minutes; buy one cheap item to a test trade link and watch `orders.lisskins_buy`, `lisskins.reconcile.tick`, the balance tile); "Snapshot stale" (`#snapshot-stale`: the scheduler's `lisskins.snapshot.failed` / `.refused` lines; `curl -sI` the export URL from the VPS; a refused tick means the export shrank by half — wait one tick, then compare `lots` in `lisskins_state`); "Balance low" (`#balance-low`: top up in the LIS-SKINS cabinet; buys refund `source_low_balance` meanwhile); "Buy failures" (`#buy-failures`: `refused` codes in the worker log, `forbidden` = key/IP, `unavailable` = their outage; open orders settle by the reconcile); "Attentions" (`rolled_back`, `ambiguous_trade`, `buy_unconfirmed`, `source_forbidden` on a LIS-SKINS order: what to check in its purchase history by `custom_id`, then «Разобрано»); "Disabling" (switch off: offers and prices leave on the next `sources.prices` tick; keep the key so the reconcile settles open orders; remove the key only when no LIS-SKINS order is open: `SELECT count(*) FROM orders WHERE source='lisskins' AND status IN ('paid','buying','trade_sent')`).

- [ ] **Step 3: Sequence diagram**

`lisskins-buy.mmd`: scheduler `lisskins.snapshot` → export (stream) → `lisskins_offers`; buyer → web → api `GET /skins/{slug}/listings` (DB read) → `POST /orders` → LIS-SKINS `check-availability` → order; worker `drain_paid` → LIS-SKINS `POST /market/buy` (`custom_id`); scheduler `lisskins.reconcile` → `GET /market/info?custom_ids[]=…` → order `trade_sent` → `delivered` (→ polled 8 days for a rollback).

- [ ] **Step 4: The rest**

- `lisskins/README.md`: what it owns (client, export reader, snapshot + roll-up, availability check, purchase records, balance), its tables and columns, the jobs (`lisskins.snapshot` 5 min, `lisskins.reconcile` 30 s — in `orders`, `lisskins.balance` 5 min, `sources.prices` 2 min), its settings, the mapping rule (Dopplers by paint index), freshness by the export's own time, tests.
- `orders/README.md`: the third source; `substitutes.py`, `purchase_rows.py`, `lisskins_{status,writes,buying,reconcile}.py`; the status table; the unconfirmed rule; trade-protection polling.
- `skins/README.md`: `lisskins_min_units` / `lisskins_count` (written by the snapshot, kept by `lisskins.rollup`), `stock_count`, `cost_units(*units)`, `TIE_ORDER`, one asset shown once, `source_prices.py`.
- `docs/architecture/module-map.md`: a `lisskins` row (depends on `core`, `skins.api`; used by `skins.source_prices`, `skins.routes`, `orders`); the `orders` row names three sources; `skins → listings` notes the three-way merge.
- `docs/security/pii-handling.md`: LIS-SKINS purchase answers carry the buyer's `steam_id` — never read or stored; `partner` / `token` only in the `market/buy` body; the key redacted (`lisskins_api_key`, `authorization`); the export holds no PII.
- `docs/api/README.md`: offer ids `ls:<digits>`; `POST /orders` re-checks a chosen `ls:` lot live (one call; a sold lot → `offer_gone` / the substitute rule, a dearer one → `price_changed`); the admin order page's `lisskins` block; the dashboard's `lisskins` balance.
- `docs/decisions/0010-skinslink-buy-source.md`: "Update 2026-10-07: LIS-SKINS joins as a third source (ADR-0012); Waxpeer buying stays off in prod (`CSMARKET_WAXPEER_BUY_ENABLED=false`); the cost is the cheapest present source."
- `AGENTS.md` §0: one sentence — "LIS-SKINS is a third buy source behind `CSMARKET_LISSKINS_ENABLED` (spec `2026-10-07-lisskins-buy-source-design.md`, ADR-0012), off until the owner switches it on". §11, after the fourth carve-out: "A fifth: `POST /orders` (ADR-0012) asks LIS-SKINS `GET /market/check-availability` once for a chosen `ls:` lot — 4 s timeout, 100 calls/min for the API, a 120 s breaker, no DB connection held across it; a failed call accepts the snapshot price (the worker's `max_price` guards). The route is already in the latency alerts' `handler` regexes."
- `docs/tech-debt.md`: (1) the admin trades page and its attention queue list Waxpeer trades only — Skinslink and LIS-SKINS attentions show on the order page, the dashboard count and the `TradeAttention` alert; (2) the export is fetched with a browser-like `User-Agent` because its CDN refused httpx's on 2026-10-07 — revisit if LIS-SKINS publishes an API for it; (3) the snapshot downloads ~855 MB every 5 minutes — watch the VPS's traffic.

- [ ] **Step 5: Gates and commit**

Run: `npx prettier --write docs AGENTS.md apps/api/src/csmarket/modules/*/README.md && npx prettier --check . && make lint`
Expected: clean.

```bash
git add docs AGENTS.md apps/api/src/csmarket/modules/*/README.md
git commit -m "docs: ADR-0012 LIS-SKINS as a buy source, runbook, module map, PII, API notes, AGENTS carve-out" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Self-review

- **Spec coverage:** §1 goals → Tasks 4–5 (cost, count, list), 9–10 (buy, deliver, refund/attention), 1 (switch). §2 constraints → Global Constraints; the banned words by prefix (Task 8) and by never reading the game field (Task 2); redaction (Task 1); ADR-0012 + §11 + alert comment (Tasks 6, 13). §3 snapshot → Task 4 (streamed, top 10, min/count, deletes, staleness, < 50 % refusal, units); sticker images through `steam_image_only` on the way out (Task 5 test). §4 prices/offers → Tasks 4 (n-ary cost, sources' tick), 5 (`ls:` ids, tie order, dedupe by asset). §5 orders/buying → Tasks 3 (`orders.source`, `lisskins_purchases`), 6 (check-availability), 7 (`substitutes.py`), 9 (the buy table row by row). §6 status flow → Tasks 8 (status table, card), 10 (one `info` call ≤ 200, unconfirmed rule). §7 settings/money/monitoring → Tasks 1, 11 (balance job, gauges, three alerts, admin block, «Разобрано» — Tasks 8 and 12). §8 tests → each task; the coverage gate → Task 1. §9 documents → Task 13. §10 rollout → the runbook's "Enabling".
- **Decisions the spec did not settle:** the scanner moves to `core/json_stream.py` with pattern arguments (Task 2); Dopplers map by paint index (Task 4); freshness by the export's own `last_update` (Task 4); `lisskins_state.lots` added for the collapse rule (Task 3); `skinslink.prices` → `sources.prices` (Task 4); delivered orders polled 8 days for rollbacks (Task 10); a `trade_create_error` without a link error refunds `sold_out` (Task 8); only the chosen `ls:` offer is checked, a lot in neither list reads "unknown", the budget is a 100/min constant (Task 6); the export is asked with a browser-like agent (Task 2); the dashboard attention count and the admin «Разобрано» now include every source (Tasks 8, 12).
- **Placeholders:** none; the existing test helpers named (`make_order`, `make_item_and_rate`, `StubListings`, `saved_trade_link`, `dev_login_headers`, `FakeTradeClient`, `FakeSkinslinkClient`, `make_skinslink_order`, the `db` fixture of `test_orders_health.py`, `_post` / `_audit` of `test_admin_orders_actions.py`, `_get` / `headers` of `test_admin_dashboard.py`) exist in `apps/api/tests/integration/`; read the target file's top before adding to it.
- **Type consistency:** `offers_for(db, skin_item_id, *, settings, now)` (both sources), `next_offer(db, *, skin_item_id, ceiling, tried, settings, waxpeer)`, `switch_source(db, order, offer)`, `pending_buy(order, *, units, key)`, `purchase_of(db, order, *, lock)`, `take_lease(db, order_id, *, source)`, `apply_report(db, *, order, purchase, report)`, `lock(db, order_id)`, `attempt_lisskins_buy(db, client, *, order_id, settings, waxpeer=None)`, `reconcile_lisskins(db_factory, client, *, settings, waxpeer=None)`, `recheck_chosen(offers, chosen, *, redis, client)`, `sync_lisskins(session_factory, redis, *, settings, reader, now)`, `sync_source_prices(session_factory, redis, *, settings, at)` are used with the same names in every task.
- **Review Focus:** each of the five lines names its test and its task above.
