# M1 — Steam Sign-in, Users, Trade Link, Admin Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A visitor signs in to csmarket.uz with Steam, sees their account page, saves a trade
link that is checked against Waxpeer and Steam, and a named admin `steam_id` opens the admin
SPA while everyone else is refused.

**Architecture:** Three backend modules ported from YuPay by allow-list — `users` (the
`users` table, Steam upsert, profile, trade link), `auth` (Steam OpenID 2.0, EdDSA access JWT
held in browser memory, rotating opaque refresh token in an `HttpOnly` cookie, Redis
blocklists, `ip_guard`), `admin` (role gate) — plus a minimal Waxpeer client that later grows
into the `skins` module. The storefront gets a header sign-in button, a Steam callback page
and `/account`; the admin SPA gets a login page, a callback route and an `AuthGuard`. A
dev-only login (force-off in prod) drives e2e without Steam.

**Tech Stack:** FastAPI · SQLAlchemy 2 async · Alembic · PyJWT (EdDSA) · httpx · Redis ·
pytest + testcontainers + respx + fakeredis · Next.js 15 + next-intl + TanStack Query ·
Vite + React Router 7 + Zustand · Playwright.

**Spec:** `docs/superpowers/specs/2026-10-01-csmarket-design.md` — §2 (decisions 4, 10),
§3.2 (`auth`, `users`, `admin` rows), §5 (`users`, `refresh_tokens`), §7.1, §7.2, §10
(`/account`, admin), §11, §13, §14, §15 row M1. Rulebook: `AGENTS.md` (§4, §9–§12, §14).

**Source material (read-only):** `/Users/macbook_uz/Projects/yupay` — written below as
`yupay:<path>`. Copy through the rename filter from the repo root:
`sed -f scripts/port-rename.sed yupay:<path> > <dst>`, then edit here. Never write to YuPay.

## Global Constraints

- **Steam is the only sign-in.** No email/password, no Google, no Telegram. Admin = the same Steam sign-in + `admin` role on named `steam_id`s. No passwords anywhere. (spec §2.4, §2.10)
- **Tokens:** access = EdDSA JWT, 15 min (`CSMARKET_JWT_ACCESS_TTL_SECONDS=900`); refresh = opaque, 30 days (`2592000`), rotating, stored only as SHA-256 in `refresh_tokens`, reuse revokes every session of the user; revocation via Redis blocklist. (spec §3.2 `auth`, §5)
- **`users` columns** exactly as spec §5 plus the ruled `trade_link_reason` (see Rulings): `id uuid pk, steam_id text unique, display_name, avatar_url, email citext null, email_verified_at null, locale (ru|uz|en), trade_link text null, trade_link_checked_at null, trade_link_verdict (ok|warn|bad|null), roles text[], banned_at, ban_reason, created_at, updated_at, deleted_at`.
- **`refresh_tokens`** exactly: `id, user_id, token_hash, expires_at, revoked_at, created_at`.
- **Trade link** (spec §7.2): pasted once (`PUT /me/trade-link`), parsed (`partner`, `token`), must belong to the signed-in `steam_id`; advisory checks Waxpeer `POST /v1/check-tradelink` + Steam `GetTradeHoldDurations`; non-zero escrow → verdict `warn` (explain, don't block); verdict cached 10 min in Redis keyed by a hash of the link; the token is never logged.
- **Never log PII:** Steam ID, email, IP, trade-link token (and the `partner` inside a link). Redis keys never contain a raw link, token or email. (spec §11, AGENTS §10)
- **Idempotency:** every state-changing endpoint accepts `Idempotency-Key` (≥ 16 chars); advisory `POST`s that write only a cached verdict say in their docstring why they are keyless. (spec §13, AGENTS §10)
- **Rate limits:** `ip_guard` (Redis, two-axis) on Steam sign-in and the trade-link check, on top of slowapi. (spec §7.1, §13)
- **External calls in handlers:** Steam OpenID `check_authentication` (it _is_ the authentication) and the advisory trade-link check (AGENTS §11 carve-out) only — 4 s timeouts on the advisory pair, 10 s on OpenID, breaker on the advisory check.
- **Locales ru / uz / en**, every key in all three in the same task; «вы»; outcome not mechanism; no service meta; inline «где взять?» hint for the trade link. (spec §11, owner rules)
- **Dev ports** (R12 from M0): api 8100, web 3100, admin 3102; in-container 8000/3000/5173. Another project (YuPay) may run on 3000/8000/3002 on the dev machine — never touch `yupay*` containers.
- **Forbidden tokens** in `apps/*/src`, `packages/*/src` (CI guard): `yupay`, `sku`, `brand_`, `supplier`, `guest_email`, `fulfiller`, `merchants`, `merchant_api`, `voucher`, `game_id`.
- **Commits:** Conventional Commits, scope `api/auth`, `api/users`, `api/admin`, `web/account`, `admin/auth`, …; trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; never push.
- **Every route change regenerates `docs/api/openapi.json`** (`cd apps/api && uv run python -m csmarket.scripts.export_openapi ../../docs/api/openapi.json`) in the same commit — CI `openapi-drift`.

## Rulings taken while planning (owner may veto)

- **P1 — Steam callback lands on the app, not the API.** Spec §7.1 says `GET /auth/steam/callback` on the API. This plan uses YuPay's proven shape: `GET /api/v1/auth/steam/start?app=web|admin&locale=…` 302s to Steam with `return_to = <app origin>/auth/steam/callback`; the app's callback page `POST`s the `openid.*` params to `/api/v1/auth/steam`, which verifies with Steam, upserts the user and sets the refresh cookie. Why: Steam shows the _site_ (`csmarket.uz`, `admin.csmarket.uz`) as the realm, not `api.csmarket.uz`, and the cookie is set by an XHR the app controls. Same verification, same cookies.
- **P2 — Access token in memory, not a cookie.** Spec §7.1 says "cookies (access …, refresh …)". The refresh token is the `HttpOnly` cookie; the access JWT is returned in the JSON body and kept in JS memory, re-minted from the cookie on load (YuPay ADR-0007 model; an XSS cannot read a 30-day session, and Bearer avoids CSRF on every write).
- **P3 — `trade_link_reason` column** (`invalid | private | trade_ban | hold | unavailable`, nullable) beside `trade_link_verdict`, so the account page can say _why_ after a reload. Spec §7.2 requires the reason; §5's column list did not carry it.
- **P4 — Email is optional and unverified in M1.** `PATCH /me {email}` stores it with `email_verified_at = null`; verification arrives with notifications (M4). No email is sent in M1.
- **P5 — Admin role is granted by a script**, `python -m csmarket.scripts.grant_admin --steam-id <id>` (roles live in `users.roles`, spec §5), not an env list. The admin audit log (`admin_audit_log`) arrives with the first admin _action_ (M3).
- **P6 — Dev login.** `POST /api/v1/auth/dev-login {steam_id, display_name?, admin?}` exists only when `CSMARKET_DEV_LOGIN_ENABLED=true` **and** `environment != prod` (404 otherwise). It drives local work and e2e without Steam (spec §14 "sign-in (mocked Steam)").
- **P7 — Ephemeral JWT keys outside prod.** If `CSMARKET_JWT_PRIVATE_KEY`/`PUBLIC_KEY` are empty and `environment != prod`, the API generates an in-process Ed25519 pair (sessions survive a restart through the refresh cookie; access tokens don't). Prod refuses to mint and `missing_prod_settings` names the keys.
- **P8 — One session cookie for web and admin.** In prod the cookie is scoped to `.csmarket.uz`, on localhost to the host; signing out of one signs out of the other. Same person, same Steam identity.
- **P9 — Waxpeer client starts in `modules/skins/waxpeer.py`** with only `check_tradelink`; M2 grows it (spec §3.2: "the Waxpeer client lives here").
- **P10 — Verdict when checks are unavailable** (no keys, breaker open, upstream error): verdict stays `null`, reason `unavailable`, the link stays saved; no Steam key → the hold check is skipped and the verdict comes from Waxpeer alone (YuPay behaviour).

## Review Focus

1. **A forged or replayed Steam callback must never open a session.** `return_to` minted for another origin, a `claimed_id` that is not `https://steamcommunity.com/openid/id/<digits>`, or Steam answering `is_valid:false` → 401 and no user row. → Task 4 `test_auth_steam.py`.
2. **A trade link of another Steam account must not be saved.** `partner + 76561197960265728 != users.steam_id` → 422 `trade_link_not_yours`, nothing written. → Task 5 `test_users_trade_link.py::test_someone_elses_link_is_refused`.
3. **Refresh-token reuse burns every session**, and two concurrent refreshes with one token can't both win. → Task 3 `test_auth_refresh.py` (ported race test).
4. **A banned account is refused at sign-in and on its very next request** (403 `account-suspended`, not 401 — the SPA must not loop refreshing). → Task 3 + Task 4 `test_user_ban.py`.
5. **Dev login is unreachable in prod** even with the flag on. → Task 4 `test_dev_login.py::test_prod_never_exposes_dev_login`.

---

## File structure (what M1 creates or changes)

```
apps/api/src/csmarket/
├── core/config.py                       + auth/steam/waxpeer/ip-guard/dev settings, PEM decode
├── bootstrap.py                         + _REQUIRED_IN_PROD entries
├── api/v1/__init__.py                   + mount auth, users, admin routers
├── modules/
│   ├── users/{__init__,api,models,identity_guard,service,tradelink,schemas,routes}.py + README.md
│   ├── auth/{__init__,api,models,jwt,security,cookies,steam,ip_guard,service,schemas,deps,routes}.py + README.md
│   ├── admin/{__init__,api,deps,routes}.py + README.md
│   └── skins/{__init__,api,waxpeer}.py + README.md
├── scripts/grant_admin.py
apps/api/migrations/versions/0002_users_auth.py
apps/api/migrations/env.py                + import users, auth models
apps/api/tests/{conftest.py (+JWT keys), unit/…, integration/…, contract/…}
apps/scheduler/src/csmarket_scheduler/{main.py, jobs/purge_refresh_tokens.py}, tests/
apps/web/src/
├── lib/{api.ts, auth.tsx, trade-link.ts} session client instance, AuthProvider, verdict copy
├── components/{Header.tsx, Providers.tsx, account/*.tsx}
├── app/[locale]/{layout.tsx, auth/steam/callback/page.tsx, account/page.tsx}
packages/api-client/src/session.ts       browser session client shared by web and admin
apps/admin/src/
├── lib/api.ts                           thin wrapper over the shared session client
├── features/auth/{authStore.ts, AuthGuard.tsx, LoginPage.tsx, SteamCallback.tsx, Forbidden.tsx}
├── app/{router.tsx, Layout.tsx}
packages/i18n/locales/{ru,uz,en}/web.json  + nav/auth/account keys
e2e/tests/{auth.spec.ts, admin.spec.ts}, e2e/playwright.config.ts (+ admin project)
docs/: decisions/0004-steam-auth-and-sessions.md, architecture/cache-keys.md, module-map.md,
       security/pii-handling.md, runbooks/admin-bootstrap.md, onboarding/local-setup.md,
       api/README.md
infra/secrets-example/api.env (+JWT/Steam/Waxpeer keys), docker-compose.yml (+dev-login env)
AGENTS.md (§0 milestone table, §13 dev-login note)
```

---

### Task 1: Auth settings, PEM decoding, test keys

**Files:**

- Modify: `apps/api/src/csmarket/core/config.py`, `apps/api/src/csmarket/bootstrap.py` (`_REQUIRED_IN_PROD`), `apps/api/tests/conftest.py`, `apps/api/.env.example`, `.env.example`, `infra/secrets-example/api.env`, `docker-compose.yml` (dev env)
- Test: `apps/api/tests/unit/test_config.py` (extend), `apps/api/tests/unit/test_bootstrap.py` (extend)

**Interfaces:**

- Produces: `Settings` fields `jwt_private_key: str`, `jwt_public_key: str`, `jwt_kid: str = "v1"`, `jwt_issuer: str = "csmarket"`, `jwt_access_ttl_seconds: int = 900`, `jwt_refresh_ttl_seconds: int = 2592000`, `admin_base_url: str = "http://localhost:3102"`, `steam_api_key: str = ""`, `waxpeer_api_key: str = ""`, `waxpeer_base_url: str = "https://api.waxpeer.com/v1"`, `dev_login_enabled: bool = False`, `auth_ip_guard_max: int = 10`, `auth_ip_guard_window_seconds: int = 60`, `auth_ip_guard_subject_max: int = 10`, `auth_ip_guard_bucket_max: dict[str, int] = {"steam-login": 60, "trade-link-check": 60, "dev-login": 60}`; property `dev_login_active: bool` (= `dev_login_enabled and not is_prod`). Session fixture env sets `CSMARKET_JWT_PRIVATE_KEY`/`PUBLIC_KEY` (fresh Ed25519) and `CSMARKET_DEV_LOGIN_ENABLED=true`.

- [ ] **Step 1: Failing tests**

Append to `apps/api/tests/unit/test_config.py`:

```python
import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def _pem() -> str:
    key = Ed25519PrivateKey.generate()
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()


def test_auth_defaults() -> None:
    s = Settings(environment="dev")
    assert s.jwt_access_ttl_seconds == 900
    assert s.jwt_refresh_ttl_seconds == 2592000
    assert s.jwt_issuer == "csmarket"
    assert s.admin_base_url == "http://localhost:3102"
    assert s.auth_ip_guard_bucket_max["steam-login"] == 60
    assert s.auth_ip_guard_bucket_max["trade-link-check"] == 60


def test_jwt_key_accepts_raw_or_base64_pem() -> None:
    pem = _pem()
    assert Settings(jwt_private_key=pem).jwt_private_key == pem
    b64 = base64.b64encode(pem.encode()).decode()
    assert Settings(jwt_private_key=b64).jwt_private_key == pem


def test_dev_login_is_never_active_in_prod() -> None:
    assert Settings(environment="dev", dev_login_enabled=True).dev_login_active is True
    assert Settings(environment="prod", dev_login_enabled=True).dev_login_active is False
    assert Settings(environment="dev", dev_login_enabled=False).dev_login_active is False
```

Append to `apps/api/tests/unit/test_bootstrap.py` (replace `test_missing_prod_settings_lists_nothing_in_m0`):

```python
def test_missing_prod_settings_names_auth_keys() -> None:
    missing = missing_prod_settings(Settings(environment="prod"))
    assert missing == [
        "CSMARKET_JWT_PRIVATE_KEY",
        "CSMARKET_JWT_PUBLIC_KEY",
        "CSMARKET_STEAM_API_KEY",
        "CSMARKET_WAXPEER_API_KEY",
    ]
```

Run: `uv run pytest apps/api/tests/unit/test_config.py apps/api/tests/unit/test_bootstrap.py -v` → FAIL (unknown fields / list mismatch).

- [ ] **Step 2: Settings**

In `core/config.py` add (module level) the PEM helper, verbatim from `yupay:apps/api/src/yupay/core/config.py` `_maybe_decode_pem`, and these fields in `Settings` (keep the existing ones; group under comments):

```python
    # --- auth (M1) ---
    admin_base_url: str = Field(
        default="http://localhost:3102", description="Public admin SPA origin (Steam return_to)."
    )
    jwt_private_key: str = Field(
        default="",
        description=(
            "Ed25519 private key, PEM or base64(PEM). Empty outside prod → an in-process "
            "ephemeral key (auth.jwt); empty in prod → minting refuses."
        ),
    )
    jwt_public_key: str = Field(default="")
    jwt_kid: str = Field(default="v1")
    jwt_issuer: str = Field(default="csmarket")
    jwt_access_ttl_seconds: int = Field(default=900)
    jwt_refresh_ttl_seconds: int = Field(default=60 * 60 * 24 * 30)
    steam_api_key: str = Field(
        default="",
        description=(
            "Steam Web API key, issued per domain. Used for persona (name, avatar) at sign-in "
            "and the trade-hold check. Empty → nameless sign-in, hold check skipped."
        ),
    )
    waxpeer_api_key: str = Field(
        default="", description="Waxpeer API key (IP-whitelisted). Empty → trade-link check unavailable."
    )
    waxpeer_base_url: str = Field(default="https://api.waxpeer.com/v1")
    dev_login_enabled: bool = Field(
        default=False,
        description="POST /auth/dev-login for local work and e2e. Ignored when environment=prod.",
    )
    auth_ip_guard_max: int = Field(default=10)
    auth_ip_guard_window_seconds: int = Field(default=60)
    auth_ip_guard_subject_max: int = Field(default=10)
    auth_ip_guard_bucket_max: dict[str, int] = Field(
        default_factory=lambda: {"steam-login": 60, "trade-link-check": 60, "dev-login": 60},
        description=(
            "Per-bucket per-IP ceilings. Uzbek mobile carriers put many subscribers behind "
            "one address, so these are crowd-sized; values <= 0 fall back to auth_ip_guard_max."
        ),
    )

    @field_validator("jwt_private_key", "jwt_public_key", mode="after")
    @classmethod
    def _decode_pem(cls, v: str) -> str:
        """Accept base64-encoded PEM blobs (single-line, .env-friendly)."""
        return _maybe_decode_pem(v)

    @property
    def dev_login_active(self) -> bool:
        """Dev login is reachable only when flagged on and never in prod."""
        return self.dev_login_enabled and not self.is_prod
```

(import `base64`, `binascii`, `field_validator`.)

In `bootstrap.py` set:

```python
_REQUIRED_IN_PROD: tuple[tuple[str, str, str], ...] = (
    ("CSMARKET_JWT_PRIVATE_KEY", "jwt_private_key", "no session can be minted: every sign-in fails"),
    ("CSMARKET_JWT_PUBLIC_KEY", "jwt_public_key", "no access token verifies: every request is 401"),
    ("CSMARKET_STEAM_API_KEY", "steam_api_key", "accounts sign in nameless; trade-hold check skipped"),
    ("CSMARKET_WAXPEER_API_KEY", "waxpeer_api_key", "trade-link check always 'unavailable'"),
)
```

- [ ] **Step 3: Test env keys**

In `apps/api/tests/conftest.py` `_test_env`, generate a fresh Ed25519 pair (as `yupay:apps/api/tests/conftest.py` does) and add to `env`: `CSMARKET_JWT_PRIVATE_KEY`, `CSMARKET_JWT_PUBLIC_KEY`, `CSMARKET_JWT_KID="test"`, `CSMARKET_DEV_LOGIN_ENABLED="true"`, `CSMARKET_STEAM_API_KEY=""`, `CSMARKET_WAXPEER_API_KEY=""`.

- [ ] **Step 4: Env templates**

- `apps/api/.env.example` and root `.env.example`: add `CSMARKET_ADMIN_BASE_URL=http://localhost:3102`, empty `CSMARKET_JWT_PRIVATE_KEY=`/`PUBLIC_KEY=` with the comment "empty in dev → ephemeral key; prod: `./scripts/gen-secret.sh jwt`", `CSMARKET_STEAM_API_KEY=`, `CSMARKET_WAXPEER_API_KEY=`, `CSMARKET_DEV_LOGIN_ENABLED=true`.
- `docker-compose.yml` `x-app-env`: `CSMARKET_ADMIN_BASE_URL: ${CSMARKET_ADMIN_BASE_URL:-http://localhost:3102}`, `CSMARKET_DEV_LOGIN_ENABLED: ${CSMARKET_DEV_LOGIN_ENABLED:-true}`, `CSMARKET_STEAM_API_KEY: ${CSMARKET_STEAM_API_KEY:-}`, `CSMARKET_WAXPEER_API_KEY: ${CSMARKET_WAXPEER_API_KEY:-}`, `CSMARKET_JWT_PRIVATE_KEY: ${CSMARKET_JWT_PRIVATE_KEY:-}`, `CSMARKET_JWT_PUBLIC_KEY: ${CSMARKET_JWT_PUBLIC_KEY:-}`.
- `infra/secrets-example/api.env`: replace the "M1 adds" comment with real entries: `CSMARKET_ADMIN_BASE_URL=https://admin.csmarket.uz`, `CSMARKET_JWT_PRIVATE_KEY=CHANGE_ME_base64_pem` / `PUBLIC_KEY` (comment: `./scripts/gen-secret.sh jwt`, base64 the PEM; rotating the private key signs everyone out), `CSMARKET_STEAM_API_KEY=CHANGE_ME_steam_web_api_key` (comment: issued per domain at steamcommunity.com/dev/apikey for csmarket.uz — YuPay's does not work), `CSMARKET_WAXPEER_API_KEY=CHANGE_ME_or_leave_empty_until_M2` (comment: IP-whitelisted to the VPS), `CSMARKET_DEV_LOGIN_ENABLED=false`.
- `scripts/gen-secret.sh jwt`: also print the base64 one-liners labelled `CSMARKET_JWT_PRIVATE_KEY=` / `CSMARKET_JWT_PUBLIC_KEY=`.

- [ ] **Step 5: Run, lint, commit**

```bash
uv run pytest apps/api/tests -q && uv run ruff check apps && uv run ruff format --check apps && uv run mypy apps
bash scripts/check-no-yupay.sh && pnpm exec prettier --check .
git add -A && git commit -m "feat(api/core): auth, Steam, Waxpeer and dev-login settings

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: `users` module — model, migration 0002 (users + refresh_tokens), Steam upsert

**Files:**

- Create: `apps/api/src/csmarket/modules/users/{__init__,api,models,identity_guard,service}.py`, `modules/users/README.md`, `apps/api/src/csmarket/modules/auth/{__init__,models}.py` (the `RefreshToken` model only — the rest of `auth` is Task 3), `apps/api/migrations/versions/0002_users_auth.py`
- Modify: `apps/api/migrations/env.py` (import `users.models`, `auth.models`), `apps/api/tests/integration/conftest.py` (`_EMPTY_IN_ORDER = ("idempotent_responses", "refresh_tokens", "users")`)
- Test: `apps/api/tests/unit/test_users_identity_guard.py`, `apps/api/tests/integration/test_users_service.py`, `apps/api/tests/integration/test_users_upsert_race.py`

**Interfaces:**

- Produces: `csmarket.modules.users.models.User` (columns per Global Constraints + `trade_link_reason`); `csmarket.modules.auth.models.RefreshToken`; `users.service.get_user_by_id(db, user_id) -> User | None`, `get_user_by_steam_id(db, steam_id: str) -> User | None`, `upsert_user_by_steam(db, *, steam_id: str, display_name: str | None, avatar_url: str | None) -> User`, `set_roles(db, user, roles: list[str]) -> None`; `users.api` re-exports those + `User`. `STEAM64_BASE = 76561197960265728` lives in `users.service`.

- [ ] **Step 1: Model**

```python
# apps/api/src/csmarket/modules/users/models.py
"""The ``users`` table — one row per Steam account (spec §5).

``steam_id`` is the identity (steamid64, stored as text: it is an identifier, never
arithmetic, and JSON clients lose precision on 64-bit ints). Everything else is profile
or state the account page edits.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ARRAY, CheckConstraint, DateTime, String, Text, text
from sqlalchemy.dialects.postgresql import CITEXT, UUID
from sqlalchemy.orm import Mapped, mapped_column

from csmarket.core.db import Base

LOCALES = ("ru", "uz", "en")
TRADE_LINK_VERDICTS = ("ok", "warn", "bad")
TRADE_LINK_REASONS = ("invalid", "private", "trade_ban", "hold", "unavailable")


class User(Base):
    """A signed-in customer (or admin — same table, ``roles`` tells them apart)."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    steam_id: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    email: Mapped[str | None] = mapped_column(CITEXT(), nullable=True)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locale: Mapped[str] = mapped_column(String(2), nullable=False, server_default="ru")
    trade_link: Mapped[str | None] = mapped_column(Text, nullable=True)
    trade_link_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    trade_link_verdict: Mapped[str | None] = mapped_column(String(8), nullable=True)
    trade_link_reason: Mapped[str | None] = mapped_column(String(16), nullable=True)
    roles: Mapped[list[str]] = mapped_column(
        ARRAY(String(32)), nullable=False, server_default=text("'{}'::varchar[]")
    )
    banned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ban_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("locale IN ('ru', 'uz', 'en')", name="locale"),
        CheckConstraint(
            "trade_link_verdict IS NULL OR trade_link_verdict IN ('ok', 'warn', 'bad')",
            name="trade_link_verdict",
        ),
        CheckConstraint(
            "trade_link_reason IS NULL OR trade_link_reason IN "
            "('invalid', 'private', 'trade_ban', 'hold', 'unavailable')",
            name="trade_link_reason",
        ),
    )
```

(Constraint names are bare suffixes — the naming convention adds `ck_users_`; see `core/db.py`.)

```python
# apps/api/src/csmarket/modules/auth/models.py
"""``refresh_tokens`` — one row per issued refresh token (spec §5).

Only the SHA-256 of the opaque token is stored. A row is a *session*: its id is the
``sid`` claim in every access token minted from it, which is what lets revoking the row
kill those access tokens at once (Redis ``auth:revoked_sid:{sid}``).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CHAR, DateTime, ForeignKey, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from csmarket.core.db import Base


class RefreshToken(Base):
    """A rotating refresh token's server-side record."""

    __tablename__ = "refresh_tokens"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
```

`modules/users/__init__.py`, `modules/auth/__init__.py`: one-line docstrings.

- [ ] **Step 2: Migration 0002**

`apps/api/migrations/versions/0002_users_auth.py` — `revision = "0002_users_auth"`, `down_revision = "0001_core_init"`. `upgrade()` creates `users` then `refresh_tokens` with exactly the columns, server defaults, check constraints (`ck_users_locale`, `ck_users_trade_link_verdict`, `ck_users_trade_link_reason` — pass the bare suffix through `op.create_table`'s `sa.CheckConstraint(..., name="locale")`, the env.py naming convention adds the prefix exactly as for the model), `uq_users_steam_id`, `uq_refresh_tokens_token_hash`, FK `fk_refresh_tokens_user_id_users` `ON DELETE CASCADE`, index `ix_refresh_tokens_user_id`, and index `ix_refresh_tokens_expires_at` + `ix_refresh_tokens_revoked_at` (the purge job's `WHERE expires_at < … OR revoked_at < …`; add `index=True` on both columns in the model too so `test_head_matches_models` stays green). `downgrade()` drops both. The existing `test_migrations.py::test_head_matches_models` is the test: it must pass after `env.py` imports both model modules.

- [ ] **Step 3: identity_guard + tests**

Copy `yupay:apps/api/src/yupay/modules/users/identity_guard.py` through the filter; trim the docstring to two sentences (third-party profile fields are guarded before they reach an INSERT; URLs over the limit are dropped, names truncated to the column width) — no YuPay incident history, no Google/Telegram mentions. Port `yupay:apps/api/tests/unit/test_users_identity_guard.py` (rename, drop provider-specific wording).

- [ ] **Step 4: Failing service tests**

```python
# apps/api/tests/integration/test_users_service.py
"""Steam upsert: one account per steamid64, profile refreshed on every sign-in."""

from __future__ import annotations

import pytest
from csmarket.modules.users.service import (
    get_user_by_steam_id,
    set_roles,
    upsert_user_by_steam,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from csmarket.modules.users.models import User

pytestmark = pytest.mark.asyncio

SID = "76561198000000001"


async def test_first_sign_in_creates_the_account(db_session: AsyncSession) -> None:
    user = await upsert_user_by_steam(
        db_session, steam_id=SID, display_name="Player", avatar_url="https://a/1.jpg"
    )
    await db_session.commit()
    assert user.steam_id == SID
    assert user.display_name == "Player"
    assert user.locale == "ru"
    assert user.roles == []


async def test_second_sign_in_reuses_it_and_refreshes_profile(db_session: AsyncSession) -> None:
    first = await upsert_user_by_steam(db_session, steam_id=SID, display_name="Old", avatar_url=None)
    await db_session.commit()
    second = await upsert_user_by_steam(
        db_session, steam_id=SID, display_name="New", avatar_url="https://a/2.jpg"
    )
    await db_session.commit()
    assert second.id == first.id
    assert second.display_name == "New"
    assert second.avatar_url == "https://a/2.jpg"
    count = (await db_session.execute(select(func.count()).select_from(User))).scalar_one()
    assert count == 1


async def test_a_missing_persona_does_not_erase_the_known_one(db_session: AsyncSession) -> None:
    await upsert_user_by_steam(db_session, steam_id=SID, display_name="Known", avatar_url="https://a/1.jpg")
    await db_session.commit()
    user = await upsert_user_by_steam(db_session, steam_id=SID, display_name=None, avatar_url=None)
    assert user.display_name == "Known"
    assert user.avatar_url == "https://a/1.jpg"


async def test_lookup_and_roles(db_session: AsyncSession) -> None:
    user = await upsert_user_by_steam(db_session, steam_id=SID, display_name=None, avatar_url=None)
    await set_roles(db_session, user, ["admin"])
    await db_session.commit()
    found = await get_user_by_steam_id(db_session, SID)
    assert found is not None
    assert found.roles == ["admin"]
```

Port `yupay:apps/api/tests/integration/test_users_upsert_race.py` → `test_users_upsert_race.py`: two sessions upserting the same `steam_id` concurrently → both return the same user id, one row. (YuPay's race was on `steam_links`; here the unique key is `users.steam_id`.)

Run `uv run pytest apps/api/tests/integration/test_users_service.py -v` → FAIL (module missing).

- [ ] **Step 5: Service**

```python
# apps/api/src/csmarket/modules/users/service.py
"""Users: find-or-create from Steam, look-ups, roles. Flushes, never commits."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.clock import now
from csmarket.core.ids import new_id
from csmarket.modules.users.identity_guard import safe_avatar_url, safe_display_name
from csmarket.modules.users.models import User

#: steamid64 = 32-bit account id (a trade link's ``partner``) + this.
STEAM64_BASE = 76561197960265728


async def get_user_by_id(db: AsyncSession, user_id: str) -> User | None:
    """The user with ``user_id``, or ``None``."""
    return await db.get(User, user_id)


async def get_user_by_steam_id(db: AsyncSession, steam_id: str) -> User | None:
    """The user owning ``steam_id``, or ``None``."""
    return (await db.execute(select(User).where(User.steam_id == steam_id))).scalar_one_or_none()


def _refresh_profile(user: User, *, display_name: str | None, avatar_url: str | None) -> None:
    """Overwrite profile fields only with values Steam actually gave us this time."""
    if display_name is not None:
        user.display_name = display_name
    if avatar_url is not None:
        user.avatar_url = avatar_url
    user.updated_at = now()


async def upsert_user_by_steam(
    db: AsyncSession,
    *,
    steam_id: str,
    display_name: str | None,
    avatar_url: str | None,
) -> User:
    """Find-or-create the account for a verified steamid64.

    Two concurrent first sign-ins for one account both see "not found"; the loser's
    INSERT hits ``uq_users_steam_id`` inside a SAVEPOINT, re-reads the winner's row and
    continues as an existing account instead of 500ing.
    """
    name = safe_display_name(display_name)
    avatar = safe_avatar_url(avatar_url)
    existing = await get_user_by_steam_id(db, steam_id)
    if existing is not None:
        _refresh_profile(existing, display_name=name, avatar_url=avatar)
        await db.flush()
        return existing
    user = User(id=new_id(), steam_id=steam_id, display_name=name, avatar_url=avatar, locale="ru", roles=[])
    try:
        async with db.begin_nested():
            db.add(user)
            await db.flush()
    except IntegrityError:
        winner = await get_user_by_steam_id(db, steam_id)
        if winner is None:  # pragma: no cover - the constraint that fired guarantees a row
            raise
        _refresh_profile(winner, display_name=name, avatar_url=avatar)
        await db.flush()
        return winner
    return user


async def set_roles(db: AsyncSession, user: User, roles: list[str]) -> None:
    """Replace ``user.roles`` (sorted, de-duplicated)."""
    user.roles = sorted(set(roles))
    user.updated_at = now()
    await db.flush()
```

`modules/users/api.py`: re-export `User`, `STEAM64_BASE`, `get_user_by_id`, `get_user_by_steam_id`, `upsert_user_by_steam`, `set_roles` (`__all__`).

- [ ] **Step 6: Run, README, commit**

```bash
uv run pytest apps/api/tests -n auto -q && uv run ruff check apps && uv run ruff format --check apps && uv run mypy apps && bash scripts/check-no-yupay.sh
```

`modules/users/README.md`: owns `users`; identity = `steam_id`; public interface = `users.api`; trade link lives here (Task 5); never log `steam_id`/email/trade link.

```bash
git add -A && git commit -m "feat(api/users): users and refresh_tokens tables, Steam upsert

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: `auth` core — JWT, refresh rotation, blocklists, current user, cookies

**Files:**

- Create: `apps/api/src/csmarket/modules/auth/{jwt,security,cookies,service,deps,schemas}.py`
- Test: `apps/api/tests/unit/test_jwt.py`, `apps/api/tests/unit/test_auth_cookies.py`, `apps/api/tests/unit/test_auth_blocklist_posture.py`, `apps/api/tests/integration/test_auth_sessions.py`, `apps/api/tests/integration/test_auth_refresh_race.py`

**Interfaces:**

- Consumes: `RefreshToken`, `User`, `users.api.get_user_by_id`, `core.redis.get_redis`, `core.errors.{UnauthorizedError, ForbiddenError}`.
- Produces:
  - `auth.jwt`: `Claims(sub, kind, jti, iat, exp, sid)`; `mint_access(*, sub: str, sid: str, settings=None) -> str`; `verify(token, *, expected_kind="access", settings=None) -> Claims`; `TokenKind = Literal["access"]`.
  - `auth.security`: `hash_token(token) -> str`, `new_refresh_token() -> str`.
  - `auth.service`: `SessionTokens(access_token, refresh_token, access_expires_in, refresh_expires_in, user)`; `open_session(db, *, user, settings=None) -> SessionTokens`; `refresh_session(db, refresh_token, *, settings=None) -> SessionTokens`; `logout(db, refresh_token, *, access_token=None, settings=None) -> None`; `resolve_current_user(db, access_token, *, settings=None) -> User`; `purge_stale_refresh_tokens(db, *, limit=5000) -> int`.
  - `core.errors.AccountSuspendedError` (403, `type` `https://csmarket.uz/errors/account-suspended`) — add it to `core/errors.py` here.
  - `auth.cookies`: `REFRESH_COOKIE_NAME = "csmarket_refresh"`, `set_refresh_cookie(response, *, token, max_age, settings)`, `clear_refresh_cookie(response, *, settings)`.
  - `auth.deps`: `current_user` FastAPI dependency (Bearer) → `User`.
  - `auth.schemas`: `TokensOut(access_token, token_type="Bearer", expires_in)`.

- [ ] **Step 1: JWT — port with deltas**

Copy `yupay:apps/api/src/yupay/modules/auth/jwt.py` through the filter, then keep only `Claims` (fields `sub, kind, jti, iat, exp, sid`), `_encode`, `_base_payload`, `mint_access` (no `tg_id`/`email_hash`), `verify`; `TokenKind = Literal["access"]`; delete every other mint function (refresh JWT, guest, ws, email, partner, merchant). Replace key access with:

```python
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

_EPHEMERAL: tuple[str, str] | None = None


def _ephemeral_pair() -> tuple[str, str]:
    """A process-local Ed25519 pair for dev/test when no keys are configured (ruling P7)."""
    global _EPHEMERAL
    if _EPHEMERAL is None:
        key = Ed25519PrivateKey.generate()
        private = key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        ).decode()
        public = key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode()
        _EPHEMERAL = (private, public)
    return _EPHEMERAL


def _keys(settings: Settings) -> tuple[str, str]:
    """(private, public). Configured keys win; prod without them refuses."""
    if settings.jwt_private_key and settings.jwt_public_key:
        return settings.jwt_private_key, settings.jwt_public_key
    if settings.is_prod:
        raise RuntimeError(
            "CSMARKET_JWT_PRIVATE_KEY / CSMARKET_JWT_PUBLIC_KEY are not configured — "
            "refusing to mint or verify. Generate with ./scripts/gen-secret.sh jwt."
        )
    return _ephemeral_pair()
```

`_encode` uses `_keys(settings)[0]`, `verify` `_keys(settings)[1]`. Add `# noqa: PLW0603` only if ruff demands it (core-style singleton). Port `yupay:apps/api/tests/unit/test_jwt.py` keeping the access-token cases (round trip, expired → 401, tampered → 401, wrong issuer → 401, `kind` mismatch → 401 — build a token with `kind="refresh"` by hand via `jwt.encode` to test the mismatch) and add:

```python
def test_prod_without_keys_refuses() -> None:
    with pytest.raises(RuntimeError, match="CSMARKET_JWT_PRIVATE_KEY"):
        mint_access(sub="u", sid="s", settings=Settings(environment="prod", jwt_private_key="", jwt_public_key=""))


def test_dev_without_keys_uses_a_stable_ephemeral_pair() -> None:
    s = Settings(environment="dev", jwt_private_key="", jwt_public_key="")
    token = mint_access(sub="u1", sid="s1", settings=s)
    assert verify(token, settings=s).sub == "u1"
```

- [ ] **Step 2: security + cookies**

`auth/security.py`: `sha256_hex`, `hash_token`, `new_refresh_token` copied from YuPay's `security.py`; nothing password-related.

`auth/cookies.py`: copy `yupay:…/auth/cookies.py` through the filter; `REFRESH_COOKIE_NAME = "csmarket_refresh"`; delete `PARTNER_REFRESH_COOKIE_NAME` and the `name=` parameter; `_cookie_domain` stays (prod → `.csmarket.uz` from `web_base_url`). Test:

```python
# apps/api/tests/unit/test_auth_cookies.py
from csmarket.core.config import Settings
from csmarket.modules.auth.cookies import REFRESH_COOKIE_NAME, set_refresh_cookie
from fastapi import Response


def _cookie(settings: Settings) -> str:
    r = Response()
    set_refresh_cookie(r, token="t" * 43, max_age=60, settings=settings)
    return r.headers["set-cookie"]


def test_dev_cookie_is_host_only_and_not_secure() -> None:
    header = _cookie(Settings(environment="dev"))
    assert header.startswith(f"{REFRESH_COOKIE_NAME}=")
    assert "HttpOnly" in header
    assert "SameSite=lax" in header
    assert "Secure" not in header
    assert "Domain" not in header


def test_prod_cookie_is_secure_and_shared_by_web_and_admin() -> None:
    header = _cookie(Settings(environment="prod", web_base_url="https://csmarket.uz"))
    assert "Secure" in header
    assert "Domain=.csmarket.uz" in header
```

- [ ] **Step 3: Failing session tests**

```python
# apps/api/tests/integration/test_auth_sessions.py
"""Sessions: open, rotate, reuse trip-wire, logout, current user, ban (Review Focus 3, 4)."""

from __future__ import annotations

import pytest
from csmarket.core.errors import AccountSuspendedError, UnauthorizedError
from csmarket.modules.auth.service import (
    logout,
    open_session,
    refresh_session,
    resolve_current_user,
)
from csmarket.modules.users.service import upsert_user_by_steam
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


async def _user(db: AsyncSession, sid: str = "76561198000000001"):  # noqa: ANN202
    return await upsert_user_by_steam(db, steam_id=sid, display_name=None, avatar_url=None)


async def test_open_session_yields_a_working_access_token(db_session: AsyncSession) -> None:
    user = await _user(db_session)
    tokens = await open_session(db_session, user=user)
    await db_session.commit()
    assert (await resolve_current_user(db_session, tokens.access_token)).id == user.id
    assert tokens.access_expires_in == 900


async def test_refresh_rotates_and_kills_the_old_access_token(db_session: AsyncSession) -> None:
    user = await _user(db_session)
    first = await open_session(db_session, user=user)
    await db_session.commit()
    second = await refresh_session(db_session, first.refresh_token)
    await db_session.commit()
    assert second.refresh_token != first.refresh_token
    with pytest.raises(UnauthorizedError):
        await resolve_current_user(db_session, first.access_token)
    assert (await resolve_current_user(db_session, second.access_token)).id == user.id


async def test_reusing_a_rotated_refresh_token_revokes_everything(db_session: AsyncSession) -> None:
    user = await _user(db_session)
    first = await open_session(db_session, user=user)
    other = await open_session(db_session, user=user)  # a second device
    await db_session.commit()
    second = await refresh_session(db_session, first.refresh_token)
    await db_session.commit()
    with pytest.raises(UnauthorizedError, match="reuse"):
        await refresh_session(db_session, first.refresh_token)
    await db_session.commit()
    for token in (second.refresh_token, other.refresh_token):
        with pytest.raises(UnauthorizedError):
            await refresh_session(db_session, token)


async def test_logout_revokes_session_and_access_token(db_session: AsyncSession) -> None:
    user = await _user(db_session)
    tokens = await open_session(db_session, user=user)
    await db_session.commit()
    await logout(db_session, tokens.refresh_token, access_token=tokens.access_token)
    await db_session.commit()
    with pytest.raises(UnauthorizedError):
        await resolve_current_user(db_session, tokens.access_token)
    with pytest.raises(UnauthorizedError):
        await refresh_session(db_session, tokens.refresh_token)


async def test_logout_with_an_unknown_token_is_a_no_op(db_session: AsyncSession) -> None:
    await logout(db_session, "never-issued")


async def test_a_banned_account_cannot_open_or_use_a_session(db_session: AsyncSession) -> None:
    from csmarket.core.clock import now

    user = await _user(db_session)
    tokens = await open_session(db_session, user=user)
    user.banned_at = now()
    await db_session.commit()
    with pytest.raises(AccountSuspendedError):
        await resolve_current_user(db_session, tokens.access_token)
    with pytest.raises(AccountSuspendedError):
        await open_session(db_session, user=user)
```

Port `yupay:apps/api/tests/integration/test_auth_refresh_race.py` (two concurrent `refresh_session` calls with one token on two engines/sessions: exactly one succeeds, the other raises reuse) and `yupay:apps/api/tests/unit/test_auth_blocklist_posture.py` (Redis error on the blocklist read → fail open, logged as `auth.blocklist_unreadable` with no key in the event), renamed.

Run → FAIL (module missing).

- [ ] **Step 4: Service**

Port from `yupay:apps/api/src/yupay/modules/auth/service.py` exactly these pieces, adapted: `SessionTokens` (drop nothing), `_open_session` → public `open_session` (no `ip_hash`/`ua_hash`, no Telegram/email claims; table `RefreshToken`, `token_hash` column), `refresh_session` (row lock `with_for_update()`, reuse → `_revoke_all_for_user`, expiry, user lookup, revoke old + `_blocklist_session_id`, open new), `_blocklist_access_token`, `_blocklist_session_id`, `logout`, `_revoke_all_for_user`, `_is_blocklisted`, `current_user` → named `resolve_current_user` (blocklists, user lookup → `UnauthorizedError("user not found")` instead of `NotFoundError`, ban → `AccountSuspendedError`), `purge_stale_refresh_tokens` (from `purge_stale_sessions`, 7-day retention, batch 5000, `RefreshToken`). Redis keys stay `auth:revoked:{jti}` and `auth:revoked_sid:{sid}`. Module docstring: "Sessions for Steam-signed-in users: open, rotate (with the reuse trip-wire), revoke, resolve. The Steam flow lives in `steam_login` (Task 4)." Drop every password/Google/Telegram/guest/email function and import.

`core/errors.py`: add

```python
class AccountSuspendedError(AppError):
    """The account is banned. 403 so SPAs don't treat it as an expired session and loop."""

    status_code = 403
    type_uri = "https://csmarket.uz/errors/account-suspended"
    title = "Account suspended"
```

`auth/deps.py`:

```python
"""FastAPI dependency resolving the signed-in user from ``Authorization: Bearer``."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.api.v1.deps import db_session
from csmarket.core.errors import UnauthorizedError
from csmarket.modules.auth.service import resolve_current_user
from csmarket.modules.users.models import User


def bearer_token(authorization: str | None) -> str:
    """The token from a ``Bearer`` header, or 401."""
    if not authorization:
        raise UnauthorizedError("missing Authorization header")
    scheme, _, token = authorization.partition(" ")
    if scheme != "Bearer" or not token.strip():
        raise UnauthorizedError("invalid Authorization scheme")
    return token.strip()


async def current_user(
    authorization: Annotated[str | None, Header()] = None,
    db: AsyncSession = Depends(db_session),  # noqa: B008
) -> User:
    """The authenticated user; 401 when absent/invalid, 403 when banned."""
    return await resolve_current_user(db, bearer_token(authorization))
```

`auth/schemas.py`: `TokensOut` from YuPay.

- [ ] **Step 5: Run, commit**

```bash
uv run pytest apps/api/tests -n auto -q && uv run ruff check apps && uv run ruff format --check apps && uv run mypy apps && bash scripts/check-no-yupay.sh
git add -A && git commit -m "feat(api/auth): EdDSA access tokens, rotating refresh sessions, blocklists

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Steam OpenID sign-in, `ip_guard`, auth routes, dev login

**Files:**

- Create: `apps/api/src/csmarket/modules/auth/{steam,ip_guard,routes,api}.py`, `modules/auth/README.md`
- Modify: `apps/api/src/csmarket/modules/auth/service.py` (+`steam_login`, `dev_login`), `auth/schemas.py`, `apps/api/src/csmarket/api/v1/__init__.py` (mount), `docs/api/openapi.json`
- Test: `apps/api/tests/integration/test_auth_steam.py`, `apps/api/tests/integration/test_auth_routes.py`, `apps/api/tests/integration/test_dev_login.py`, `apps/api/tests/integration/test_auth_ip_guard.py`, `apps/api/tests/unit/test_ip_guard_buckets.py`

**Interfaces:**

- Consumes: Task 3 service/cookies/schemas; `users.api.upsert_user_by_steam`, `set_roles`; `core.metrics.steam_web_api_call`.
- Produces:
  - `auth.steam`: `SteamAuthError`, `build_login_url(*, return_to, realm) -> str`, `verify_callback(params, *, expected_return_prefix, http=None) -> int`, `fetch_persona(steam_id: int, *, api_key, http=None) -> tuple[str | None, str | None]`, `trade_hold_days(steam_id: int, token: str, *, api_key, http=None) -> int | None` (used by Task 5).
  - `auth.ip_guard`: `guard_ip(request, *, bucket: str, subject: str | None = None) -> None`, `hit_counter(key, *, limit, window) -> bool`, `bucket_limit(settings, bucket) -> int`.
  - `auth.service.steam_login(db, params, *, app: AppName, settings=None, verifier=None, persona=None) -> SessionTokens`; `AppName = Literal["web", "admin"]`; `callback_url(settings, app) -> str` (`<origin>/auth/steam/callback`, origin = `web_base_url` or `admin_base_url`); `dev_login(db, *, steam_id: str, display_name: str | None, admin: bool) -> SessionTokens`.
  - HTTP: `GET /api/v1/auth/steam/start?app=web|admin&locale=ru|uz|en` → 302 Steam; `POST /api/v1/auth/steam {app, params}` → `TokensOut` + refresh cookie; `POST /api/v1/auth/refresh` (cookie) → `TokensOut` + rotated cookie; `POST /api/v1/auth/logout` → 204 + cookie cleared; `POST /api/v1/auth/dev-login {steam_id, display_name?, admin?}` → `TokensOut` + cookie (404 unless `dev_login_active`).
  - `auth.api` re-exports: `router`, `current_user` (dep), `SessionTokens`, `TokensOut`, `guard_ip`, `trade_hold_days`.

- [ ] **Step 1: steam.py — port with deltas**

Copy `yupay:apps/api/src/yupay/modules/auth/steam.py` through the filter, then: module docstring — keep paragraphs 1–2, replace the last with "Identity is the steamid64 alone; `users.steam_id` holds it as text."; in `trade_hold_days` the default `consumer` becomes `"trade_link"`; `resolve_persona`'s long docstring trimmed to its contract (None = Steam says no such account; pair of Nones = account with nothing to render; raises `httpx.HTTPError`/`ValueError`), dropping gift-check history. `__all__` adds `trade_hold_days`. Port `yupay:apps/api/tests/contract/test_steam_trade_hold.py` → `apps/api/tests/contract/test_steam_trade_hold.py` (create `tests/contract/__init__.py`) with respx: 0 s → 0 days, 86400·7 s → 7, missing number → None, 500 → `httpx.HTTPStatusError`; token never in logs (capture structlog output, assert the token string absent).

- [ ] **Step 2: ip_guard.py — port**

Copy `yupay:…/auth/ip_guard.py` through the filter; docstring: drop the player-check paragraph, keep the carrier-NAT two-axis rationale; key the IP axis on `hash_short(ip)` from `core.logging` instead of the raw IP (`auth:ipguard:{bucket}:{hash_short(ip)}` and the subject key `auth:ipguard:{bucket}:{hash_short(ip)}:s:{digest}`) — a Redis key is not a log, but `MONITOR`/`SCAN` read it and the owner rule says no IPs at rest. Port `yupay:apps/api/tests/unit/test_ip_guard_buckets.py` and `yupay:apps/api/tests/integration/test_auth_ip_guard.py` (bucket over limit → 429 with `Retry-After`; Redis down → fail open), and add one assertion that no Redis key contains the literal client IP (`[k async for k in redis.scan_iter("auth:ipguard:*")]`).

- [ ] **Step 3: Failing Steam + route tests**

`apps/api/tests/integration/test_auth_steam.py` — port `yupay:apps/api/tests/integration/test_auth_steam.py` with `https://csmarket.uz` / `http://localhost:3100` bases and these csmarket cases (Review Focus 1):

```python
import httpx
import pytest
import respx
from csmarket.core.config import Settings
from csmarket.core.errors import UnauthorizedError
from csmarket.modules.auth.service import callback_url, steam_login
from csmarket.modules.auth.steam import SteamAuthError, build_login_url, verify_callback
from csmarket.modules.users.models import User
from sqlalchemy import func, select

pytestmark = pytest.mark.asyncio
_OPENID = "https://steamcommunity.com/openid/login"
WEB = Settings(environment="test", web_base_url="https://csmarket.uz", admin_base_url="https://admin.csmarket.uz")


def _params(*, return_to: str = "https://csmarket.uz/auth/steam/callback?locale=ru", sid: str = "76561198000000001") -> dict[str, str]:
    return {
        "openid.ns": "http://specs.openid.net/auth/2.0",
        "openid.mode": "id_res",
        "openid.claimed_id": f"https://steamcommunity.com/openid/id/{sid}",
        "openid.return_to": return_to,
        "openid.sig": "sig",
        "openid.signed": "signed,fields",
    }


def test_callback_urls_per_app() -> None:
    assert callback_url(WEB, "web") == "https://csmarket.uz/auth/steam/callback"
    assert callback_url(WEB, "admin") == "https://admin.csmarket.uz/auth/steam/callback"


async def test_an_admin_assertion_cannot_open_a_web_session(db_session) -> None:  # noqa: ANN001
    async def verifier(params, *, expected_return_prefix):  # noqa: ANN001, ANN202
        return await verify_callback(params, expected_return_prefix=expected_return_prefix)

    with pytest.raises(UnauthorizedError):
        await steam_login(
            db_session,
            _params(return_to="https://admin.csmarket.uz/auth/steam/callback"),
            app="web",
            settings=WEB,
            verifier=verifier,
        )
    assert (await db_session.execute(select(func.count()).select_from(User))).scalar_one() == 0


@respx.mock
async def test_steam_saying_no_creates_nobody(db_session) -> None:  # noqa: ANN001
    respx.post(_OPENID).mock(return_value=httpx.Response(200, text="is_valid:false\n"))
    with pytest.raises(UnauthorizedError):
        await steam_login(db_session, _params(), app="web", settings=WEB)
    assert (await db_session.execute(select(func.count()).select_from(User))).scalar_one() == 0


async def test_a_non_steam_claimed_id_is_refused_before_any_traffic() -> None:
    params = _params()
    params["openid.claimed_id"] = "https://evil.example/openid/id/76561198000000001"
    with pytest.raises(SteamAuthError):
        await verify_callback(params, expected_return_prefix="https://csmarket.uz/auth/steam/callback")


@respx.mock
async def test_valid_assertion_signs_in_and_stores_steam_id_as_text(db_session) -> None:  # noqa: ANN001
    respx.post(_OPENID).mock(return_value=httpx.Response(200, text="is_valid:true\n"))
    tokens = await steam_login(db_session, _params(), app="web", settings=WEB)
    await db_session.commit()
    assert tokens.user.steam_id == "76561198000000001"
```

`apps/api/tests/integration/test_auth_routes.py` (through `integration_client`):

```python
import httpx
import pytest
import respx
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio
_OPENID = "https://steamcommunity.com/openid/login"


async def test_start_redirects_to_steam_with_the_app_callback(integration_client: AsyncClient) -> None:
    r = await integration_client.get("/api/v1/auth/steam/start", params={"app": "admin", "locale": "uz"})
    assert r.status_code == 302
    loc = r.headers["location"]
    assert loc.startswith(_OPENID)
    assert "localhost%3A3102%2Fauth%2Fsteam%2Fcallback" in loc  # admin_base_url default
    assert "locale%3Duz" in loc


async def test_start_rejects_an_unknown_app(integration_client: AsyncClient) -> None:
    r = await integration_client.get("/api/v1/auth/steam/start", params={"app": "https://evil.example"})
    assert r.status_code == 422


@respx.mock
async def test_steam_post_sets_cookie_and_refresh_rotates_it(integration_client: AsyncClient) -> None:
    respx.post(_OPENID).mock(return_value=httpx.Response(200, text="is_valid:true\n"))
    params = {
        "openid.ns": "http://specs.openid.net/auth/2.0",
        "openid.mode": "id_res",
        "openid.claimed_id": "https://steamcommunity.com/openid/id/76561198000000001",
        "openid.return_to": "http://localhost:3100/auth/steam/callback?locale=ru",
        "openid.sig": "s",
        "openid.signed": "a,b",
    }
    r = await integration_client.post("/api/v1/auth/steam", json={"app": "web", "params": params})
    assert r.status_code == 200, r.text
    assert r.json()["token_type"] == "Bearer"
    first_cookie = integration_client.cookies.get("csmarket_refresh")
    assert first_cookie
    r2 = await integration_client.post("/api/v1/auth/refresh")
    assert r2.status_code == 200
    assert integration_client.cookies.get("csmarket_refresh") != first_cookie


async def test_refresh_without_cookie_is_401(integration_client: AsyncClient) -> None:
    assert (await integration_client.post("/api/v1/auth/refresh")).status_code == 401


async def test_logout_clears_the_cookie(integration_client: AsyncClient) -> None:
    await integration_client.post("/api/v1/auth/dev-login", json={"steam_id": "76561198000000002"})
    r = await integration_client.post("/api/v1/auth/logout")
    assert r.status_code == 204
    assert integration_client.cookies.get("csmarket_refresh") is None
    assert (await integration_client.post("/api/v1/auth/refresh")).status_code == 401
```

(The test `Settings` default `web_base_url` is `http://localhost:3000` from M0 — set `CSMARKET_WEB_BASE_URL=http://localhost:3100` in the session env of `tests/conftest.py` so tests use the dev origin; adjust `test_config.py`'s defaults test only if it asserts that field.)

`apps/api/tests/integration/test_dev_login.py` (Review Focus 5):

```python
import pytest
from csmarket.core import config as cfg
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def test_dev_login_opens_a_session_and_can_grant_admin(
    integration_client: AsyncClient, db_session
) -> None:  # noqa: ANN001
    from csmarket.modules.users.service import get_user_by_steam_id

    r = await integration_client.post(
        "/api/v1/auth/dev-login", json={"steam_id": "76561198000000003", "display_name": "Dev", "admin": True}
    )
    assert r.status_code == 200
    assert r.json()["token_type"] == "Bearer"
    assert integration_client.cookies.get("csmarket_refresh")
    user = await get_user_by_steam_id(db_session, "76561198000000003")
    assert user is not None
    assert user.roles == ["admin"]
    assert user.display_name == "Dev"


async def test_dev_login_rejects_a_non_steam_id(integration_client: AsyncClient) -> None:
    r = await integration_client.post("/api/v1/auth/dev-login", json={"steam_id": "abc"})
    assert r.status_code == 422


async def test_prod_never_exposes_dev_login(monkeypatch, db_engine) -> None:  # noqa: ANN001
    from csmarket.bootstrap import create_app
    from httpx import ASGITransport

    monkeypatch.setenv("CSMARKET_ENVIRONMENT", "prod")
    monkeypatch.setenv("CSMARKET_DEV_LOGIN_ENABLED", "true")
    cfg.get_settings.cache_clear()
    try:
        app = create_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            r = await c.post("/api/v1/auth/dev-login", json={"steam_id": "76561198000000003"})
        assert r.status_code == 404
    finally:
        monkeypatch.undo()
        cfg.get_settings.cache_clear()
```

Run → FAIL.

- [ ] **Step 4: Service additions**

```python
# in auth/service.py
AppName = Literal["web", "admin"]


def callback_url(settings: Settings, app: AppName) -> str:
    """Where Steam returns the browser for ``app`` — also the only accepted ``return_to``."""
    origin = settings.admin_base_url if app == "admin" else settings.web_base_url
    return f"{origin.rstrip('/')}/auth/steam/callback"


async def steam_login(
    db: AsyncSession,
    params: dict[str, str],
    *,
    app: AppName,
    settings: Settings | None = None,
    verifier: Callable[..., Awaitable[int]] | None = None,
    persona: Callable[..., Awaitable[tuple[str | None, str | None]]] | None = None,
) -> SessionTokens:
    """Verify a Steam OpenID callback for ``app`` and open a session.

    Raises:
        UnauthorizedError: verification failed (foreign ``return_to``, bad ``claimed_id``,
            Steam said no, Steam unreachable).
        AccountSuspendedError: the account is banned.
    """
    s = settings or get_settings()
    verify = verifier or steam.verify_callback
    try:
        steam_id = await verify(params, expected_return_prefix=callback_url(s, app))
    except steam.SteamAuthError as exc:
        log.info("auth.steam.rejected", reason=str(exc))
        raise UnauthorizedError("steam verification failed") from exc
    name: str | None = None
    avatar: str | None = None
    if s.steam_api_key:
        fetch = persona or steam.fetch_persona
        name, avatar = await fetch(steam_id, api_key=s.steam_api_key)
    user = await upsert_user_by_steam(db, steam_id=str(steam_id), display_name=name, avatar_url=avatar)
    return await open_session(db, user=user, settings=s)


async def dev_login(
    db: AsyncSession, *, steam_id: str, display_name: str | None, admin: bool
) -> SessionTokens:
    """Dev/e2e only (ruling P6). The route refuses unless ``settings.dev_login_active``."""
    user = await upsert_user_by_steam(db, steam_id=steam_id, display_name=display_name, avatar_url=None)
    if admin:
        await set_roles(db, user, [*user.roles, "admin"])
    return await open_session(db, user=user)
```

(`SteamAuthError` messages must never carry the steamid; YuPay's don't.)

- [ ] **Step 5: Schemas + routes**

```python
# additions to auth/schemas.py
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SteamCallbackIn(BaseModel):
    """The ``openid.*`` params exactly as Steam appended them, and which app asked."""

    model_config = ConfigDict(extra="forbid")

    app: Literal["web", "admin"]
    params: dict[str, str] = Field(min_length=4, max_length=32)


class DevLoginIn(BaseModel):
    """Dev/e2e sign-in (ruling P6)."""

    model_config = ConfigDict(extra="forbid")

    steam_id: str = Field(pattern=r"^7656119\d{10}$")
    display_name: str | None = Field(default=None, max_length=64)
    admin: bool = False
```

```python
# apps/api/src/csmarket/modules/auth/routes.py
"""``/api/v1/auth`` — Steam sign-in, refresh rotation, logout, dev login."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Cookie, Depends, Header, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.api.v1.deps import db_session
from csmarket.core.config import get_settings
from csmarket.core.errors import NotFoundError, UnauthorizedError
from csmarket.modules.auth import steam
from csmarket.modules.auth.cookies import REFRESH_COOKIE_NAME, clear_refresh_cookie, set_refresh_cookie
from csmarket.modules.auth.ip_guard import guard_ip
from csmarket.modules.auth.schemas import DevLoginIn, SteamCallbackIn, TokensOut
from csmarket.modules.auth.service import (
    SessionTokens,
    callback_url,
    dev_login,
    logout,
    refresh_session,
    steam_login,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _session_response(response: Response, tokens: SessionTokens) -> TokensOut:
    """Refresh token → HttpOnly cookie; access token → body (ruling P2)."""
    set_refresh_cookie(
        response, token=tokens.refresh_token, max_age=tokens.refresh_expires_in, settings=get_settings()
    )
    return TokensOut(access_token=tokens.access_token, expires_in=tokens.access_expires_in)


@router.get("/steam/start", summary="Begin a Steam sign-in (302 to steamcommunity.com)")
async def steam_start(
    app: Annotated[Literal["web", "admin"], Query()] = "web",
    locale: Annotated[Literal["ru", "uz", "en"], Query()] = "ru",
) -> RedirectResponse:
    """``return_to`` is the app's own callback page; realm is the app's origin."""
    s = get_settings()
    back = callback_url(s, app)
    realm = s.admin_base_url if app == "admin" else s.web_base_url
    url = steam.build_login_url(return_to=f"{back}?locale={locale}", realm=realm.rstrip("/"))
    return RedirectResponse(url, status_code=status.HTTP_302_FOUND)


@router.post("/steam", response_model=TokensOut, summary="Complete a Steam sign-in")
async def steam_complete(
    body: SteamCallbackIn,
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(db_session)],
) -> TokensOut:
    """Verify the callback with Steam and open a session.

    Keyless by design: replaying an OpenID assertion is refused by Steam itself
    (``check_authentication`` succeeds once), so an ``Idempotency-Key`` adds nothing.
    """
    await guard_ip(request, bucket="steam-login")
    tokens = await steam_login(db, body.params, app=body.app)
    return _session_response(response, tokens)


@router.post("/refresh", response_model=TokensOut, summary="Rotate the refresh cookie")
async def refresh(
    response: Response,
    db: Annotated[AsyncSession, Depends(db_session)],
    refresh_token: Annotated[str | None, Cookie(alias=REFRESH_COOKIE_NAME)] = None,
) -> TokensOut:
    """Rotate-on-use; the reuse trip-wire lives in the service. Keyless: rotation is
    inherently single-use, a replay is the attack it detects."""
    if not refresh_token:
        raise UnauthorizedError("missing refresh token")
    tokens = await refresh_session(db, refresh_token)
    return _session_response(response, tokens)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Sign out")
async def logout_route(
    response: Response,
    db: Annotated[AsyncSession, Depends(db_session)],
    authorization: Annotated[str | None, Header()] = None,
    refresh_token: Annotated[str | None, Cookie(alias=REFRESH_COOKIE_NAME)] = None,
) -> None:
    """Idempotent: unknown or already-revoked tokens succeed silently."""
    access: str | None = None
    if authorization:
        scheme, _, tok = authorization.partition(" ")
        if scheme == "Bearer" and tok.strip():
            access = tok.strip()
    await logout(db, refresh_token or "", access_token=access)
    clear_refresh_cookie(response, settings=get_settings())


@router.post("/dev-login", response_model=TokensOut, include_in_schema=False)
async def dev_login_route(
    body: DevLoginIn,
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(db_session)],
) -> TokensOut:
    """Local work and e2e only; 404 unless ``dev_login_active`` (never in prod)."""
    if not get_settings().dev_login_active:
        raise NotFoundError("not found")
    await guard_ip(request, bucket="dev-login")
    tokens = await dev_login(db, steam_id=body.steam_id, display_name=body.display_name, admin=body.admin)
    return _session_response(response, tokens)
```

`include_in_schema=False` keeps dev-login out of `openapi.json` (and the generated client). `auth/api.py` re-exports per Interfaces. Mount in `api/v1/__init__.py`: `router.include_router(auth_router)` (import from `csmarket.modules.auth.api`).

- [ ] **Step 6: Run, regen schema, README, commit**

```bash
uv run pytest apps/api/tests -n auto -q && uv run ruff check apps && uv run ruff format --check apps && uv run mypy apps && bash scripts/check-no-yupay.sh
cd apps/api && uv run python -m csmarket.scripts.export_openapi ../../docs/api/openapi.json && cd ../..
```

`modules/auth/README.md`: responsibilities, public interface (`auth.api`), table `refresh_tokens`, token model table (access 15 min in memory / refresh 30 d `csmarket_refresh` HttpOnly cookie), HTTP surface table (the five routes; dev-login dev-only), Redis keys (`auth:revoked:{jti}`, `auth:revoked_sid:{sid}`, `auth:ipguard:*`), the two external calls (OpenID check — 10 s; persona — 5 s, best-effort).

```bash
git add -A && git commit -m "feat(api/auth): Steam OpenID sign-in, refresh/logout routes, ip_guard, dev login

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

---

### Task 5: `/me`, profile, trade link with advisory check; minimal Waxpeer client

**Files:**

- Create: `apps/api/src/csmarket/modules/skins/{__init__,api,waxpeer}.py`, `modules/skins/README.md`, `apps/api/src/csmarket/modules/users/{tradelink,schemas,routes}.py`
- Modify: `modules/users/service.py` (+`update_profile`, `save_trade_link`, `record_trade_link_check`), `modules/users/api.py`, `api/v1/__init__.py` (mount users router), `apps/api/pyproject.toml` (+`email-validator>=2.2`), `uv.lock`, `docs/api/openapi.json`, `infra/prometheus/alerts/api.yml` (regex already matches `/me/trade-link/check` via `/trade-?link/check` — verify, change nothing if it does)
- Test: `apps/api/tests/unit/test_users_tradelink.py`, `apps/api/tests/contract/test_waxpeer_check_tradelink.py`, `apps/api/tests/integration/test_users_routes.py`, `apps/api/tests/integration/test_users_trade_link.py`

**Interfaces:**

- Consumes: `auth.api.current_user`, `auth.api.guard_ip`, `auth.api.trade_hold_days`, `users.service.STEAM64_BASE`, `core.idempotency.{normalize_idempotency_key, load_replay, save_replay, IDEMPOTENCY_HEADER}`, `core.redis.get_redis`.
- Produces:
  - `skins.waxpeer`: `WaxpeerClient(*, api_key: str, base_url: str, timeout_seconds: float, client: httpx.AsyncClient | None = None)` with `async check_tradelink(url) -> str | None`; `WaxpeerError(message, *, status=200, body="")`; `WaxpeerUnavailableError`. `skins.api` re-exports them.
  - `users.tradelink`: `TradeLink(url, partner: int, token: str)` with `.steam_id -> str`; `parse_tradelink(raw) -> TradeLink` (raises `ValidationError(code="trade_link_invalid")`); `assert_owned(link, steam_id: str) -> None` (raises `ValidationError(code="trade_link_not_yours")`); `CheckResult(verdict: Literal["ok","warn","bad"] | None, reason: Reason | None)`; `TradelinkChecker`/`HoldChecker` protocols; `check_trade_link(link, *, waxpeer, hold, redis) -> CheckResult`; constants `CACHE_TTL_SECONDS = 600`, `BREAKER_TTL_SECONDS = 60`, keys `users:tradelink:{digest}` / `users:tradelink:breaker`.
  - `users.schemas`: `MeOut`, `MePatchIn(locale: Literal["ru","uz","en"] | None, email: EmailStr | None)`, `TradeLinkIn(url: str ≤ 300)`, `TradeLinkOut(trade_link: str | None, verdict, reason, checked_at)`.
  - HTTP: `GET /api/v1/me` → `MeOut`; `PATCH /api/v1/me` → `MeOut`; `PUT /api/v1/me/trade-link` → `TradeLinkOut`; `POST /api/v1/me/trade-link/check` → `TradeLinkOut`. Dependency `tradelink_checkers() -> tuple[TradelinkChecker, HoldChecker]` overridable in tests.

- [ ] **Step 1: Waxpeer client (contract-tested)**

```python
# apps/api/src/csmarket/modules/skins/waxpeer.py
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
    """Waxpeer could not be reached, or no API key is configured."""


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
        self, method: str, path: str, *, json: dict[str, Any] | None = None
    ) -> dict[str, Any]:
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
        body = resp.json()
        if not isinstance(body, dict):
            raise WaxpeerError("unexpected body", body=resp.text)
        if not body.get("success", False):
            raise WaxpeerError(str(body.get("msg") or "refused"), body=resp.text)
        return body

    async def check_tradelink(self, url: str) -> str | None:
        """``POST /v1/check-tradelink``: ``None`` when the link works, else Steam's reason.

        ``success: true`` with ``info`` (private inventory, trade ban) and ``success: false``
        with ``msg`` (a link Waxpeer won't use) both come back as reason text; a transport
        failure or HTTP error raises.
        """
        try:
            body = await self._request("POST", "/check-tradelink", json={"tradelink": url})
        except WaxpeerError as exc:
            if exc.status == 200:
                return str(exc) or "refused"
            raise
        info = body.get("info")
        return str(info) if info else None
```

`skins/__init__.py` docstring "CS2 catalogue and Waxpeer (M2); M1 ships only the client." `skins/api.py` re-exports the three names.

```python
# apps/api/tests/contract/test_waxpeer_check_tradelink.py
import httpx
import pytest
import respx
from csmarket.modules.skins.waxpeer import WaxpeerClient, WaxpeerError, WaxpeerUnavailableError

pytestmark = pytest.mark.asyncio
URL = "https://api.waxpeer.com/v1/check-tradelink"
LINK = "https://steamcommunity.com/tradeoffer/new/?partner=39734273&token=AbCdEf12"


def _client(key: str = "k") -> WaxpeerClient:
    return WaxpeerClient(api_key=key, base_url="https://api.waxpeer.com/v1", timeout_seconds=1)


@respx.mock
async def test_working_link_is_none_and_key_rides_the_query() -> None:
    route = respx.post(URL).mock(return_value=httpx.Response(200, json={"success": True}))
    assert await _client().check_tradelink(LINK) is None
    assert route.calls[0].request.url.params["api"] == "k"


@respx.mock
async def test_info_is_the_reason() -> None:
    respx.post(URL).mock(return_value=httpx.Response(200, json={"success": True, "info": "Inventory is private"}))
    assert await _client().check_tradelink(LINK) == "Inventory is private"


@respx.mock
async def test_success_false_is_a_reason_not_an_error() -> None:
    respx.post(URL).mock(return_value=httpx.Response(200, json={"success": False, "msg": "Invalid tradelink"}))
    assert await _client().check_tradelink(LINK) == "Invalid tradelink"


@respx.mock
async def test_http_error_raises() -> None:
    respx.post(URL).mock(return_value=httpx.Response(502, text="bad gateway"))
    with pytest.raises(WaxpeerError):
        await _client().check_tradelink(LINK)


async def test_no_key_is_unavailable_without_traffic() -> None:
    with pytest.raises(WaxpeerUnavailableError):
        await _client("").check_tradelink(LINK)


@respx.mock
async def test_timeout_is_unavailable() -> None:
    respx.post(URL).mock(side_effect=httpx.ConnectTimeout("t"))
    with pytest.raises(WaxpeerUnavailableError):
        await _client().check_tradelink(LINK)
```

The `LINK` uses a redrawn fake partner/token — never a real one (owner rule).

- [ ] **Step 2: Failing trade-link unit tests**

```python
# apps/api/tests/unit/test_users_tradelink.py
"""Trade link: parse, ownership, verdict mapping, cache, breaker (spec §7.2)."""

from __future__ import annotations

import fakeredis.aioredis
import pytest
from csmarket.core.errors import ValidationError
from csmarket.modules.users.tradelink import (
    CheckResult,
    assert_owned,
    check_trade_link,
    parse_tradelink,
)

pytestmark = pytest.mark.asyncio
OWNER = "76561198000000001"  # partner 39734273
LINK = "https://steamcommunity.com/tradeoffer/new/?partner=39734273&token=AbCdEf12"


class _Wax:
    def __init__(self, info: str | None = None, exc: Exception | None = None) -> None:
        self.info, self.exc, self.calls = info, exc, 0

    async def check_tradelink(self, url: str) -> str | None:
        self.calls += 1
        if self.exc:
            raise self.exc
        return self.info


class _Hold:
    def __init__(self, days: int | None = 0) -> None:
        self.days, self.calls = days, 0

    async def trade_hold_days(self, steam_id: str, token: str) -> int | None:
        self.calls += 1
        return self.days


@pytest.fixture
def redis():  # noqa: ANN201
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


def test_parse_accepts_steams_own_link_and_trims() -> None:
    link = parse_tradelink(f"  {LINK} ")
    assert (link.partner, link.token, link.steam_id) == (39734273, "AbCdEf12", OWNER)


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "https://steamcommunity.com/tradeoffer/new/?partner=39734273",
        "http://steamcommunity.com/tradeoffer/new/?partner=39734273&token=AbCdEf12",
        "https://steamcommunity.com.evil/tradeoffer/new/?partner=39734273&token=AbCdEf12",
        "https://steamcommunity.com/tradeoffer/new/?partner=abc&token=AbCdEf12",
    ],
)
def test_parse_rejects_anything_else(raw: str) -> None:
    with pytest.raises(ValidationError) as exc:
        parse_tradelink(raw)
    assert exc.value.extra["code"] == "trade_link_invalid"


def test_ownership() -> None:
    assert_owned(parse_tradelink(LINK), OWNER)
    with pytest.raises(ValidationError) as exc:
        assert_owned(parse_tradelink(LINK), "76561198000000002")
    assert exc.value.extra["code"] == "trade_link_not_yours"


@pytest.mark.parametrize(
    ("info", "days", "expected"),
    [
        (None, 0, CheckResult(verdict="ok", reason=None)),
        (None, None, CheckResult(verdict="ok", reason=None)),  # no Steam number → Waxpeer alone
        (None, 7, CheckResult(verdict="warn", reason="hold")),
        ("Inventory is private", 0, CheckResult(verdict="bad", reason="private")),
        ("User has trade ban", 0, CheckResult(verdict="bad", reason="trade_ban")),
        ("Invalid tradelink", 0, CheckResult(verdict="bad", reason="invalid")),
    ],
)
async def test_verdict_mapping(redis, info, days, expected) -> None:  # noqa: ANN001
    result = await check_trade_link(parse_tradelink(LINK), waxpeer=_Wax(info), hold=_Hold(days), redis=redis)
    assert result == expected


async def test_bad_link_skips_the_hold_call(redis) -> None:  # noqa: ANN001
    hold = _Hold(7)
    await check_trade_link(parse_tradelink(LINK), waxpeer=_Wax("private"), hold=hold, redis=redis)
    assert hold.calls == 0


async def test_cached_for_ten_minutes_and_key_has_no_token(redis) -> None:  # noqa: ANN001
    wax = _Wax()
    for _ in range(2):
        await check_trade_link(parse_tradelink(LINK), waxpeer=wax, hold=_Hold(0), redis=redis)
    assert wax.calls == 1
    keys = [k async for k in redis.scan_iter("users:tradelink:*")]
    assert keys and all("AbCdEf12" not in k and "39734273" not in k for k in keys)
    assert 590 <= await redis.ttl(keys[0]) <= 600


async def test_outage_is_unavailable_and_opens_the_breaker(redis) -> None:  # noqa: ANN001
    from csmarket.modules.skins.waxpeer import WaxpeerUnavailableError

    first = await check_trade_link(
        parse_tradelink(LINK), waxpeer=_Wax(exc=WaxpeerUnavailableError("x")), hold=_Hold(), redis=redis
    )
    assert first == CheckResult(verdict=None, reason="unavailable")
    wax = _Wax()
    second = await check_trade_link(parse_tradelink(LINK), waxpeer=wax, hold=_Hold(), redis=redis)
    assert second == CheckResult(verdict=None, reason="unavailable")
    assert wax.calls == 0  # breaker open: no upstream call
    assert 50 <= await redis.ttl("users:tradelink:breaker") <= 60


async def test_unavailable_is_not_cached(redis) -> None:  # noqa: ANN001
    from csmarket.modules.skins.waxpeer import WaxpeerUnavailableError

    await check_trade_link(
        parse_tradelink(LINK), waxpeer=_Wax(exc=WaxpeerUnavailableError("x")), hold=_Hold(), redis=redis
    )
    await redis.delete("users:tradelink:breaker")
    result = await check_trade_link(parse_tradelink(LINK), waxpeer=_Wax(), hold=_Hold(0), redis=redis)
    assert result.verdict == "ok"
```

Run → FAIL (module missing).

- [ ] **Step 3: `users/tradelink.py`**

```python
# apps/api/src/csmarket/modules/users/tradelink.py
"""The customer's Steam trade link: parse, prove ownership, advisory check (spec §7.2).

The ``token`` in a trade link lets anyone send that account offers — a credential. It is
never logged and never part of a Redis key (keys use a SHA-256 digest of the link).
The check asks Waxpeer whether the link works (private inventory, trade ban) and Steam
whether a trade would be held (no mobile authenticator → escrow). It is advisory: any
upstream failure answers ``unavailable`` and opens a 60-second breaker (AGENTS §11).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Literal, Protocol

from redis.asyncio import Redis
from redis.exceptions import RedisError

from csmarket.core.errors import ValidationError
from csmarket.core.logging import get_logger
from csmarket.modules.users.service import STEAM64_BASE

log = get_logger("csmarket.users.tradelink")

_LINK = re.compile(
    r"^https://steamcommunity\.com/tradeoffer/new/\?partner=(\d{1,12})&token=([\w-]{6,16})$"
)
CACHE_TTL_SECONDS = 600
BREAKER_TTL_SECONDS = 60
_CACHE_PREFIX = "users:tradelink:"
BREAKER_KEY = "users:tradelink:breaker"

Verdict = Literal["ok", "warn", "bad"]
Reason = Literal["invalid", "private", "trade_ban", "hold", "unavailable"]


@dataclass(frozen=True, slots=True)
class TradeLink:
    """A parsed trade link."""

    url: str
    partner: int
    token: str

    @property
    def steam_id(self) -> str:
        """The account's steamid64, as ``users.steam_id`` stores it."""
        return str(self.partner + STEAM64_BASE)


@dataclass(frozen=True, slots=True)
class CheckResult:
    """``verdict`` is ``None`` only when the check could not run (``reason="unavailable"``)."""

    verdict: Verdict | None
    reason: Reason | None


class TradelinkChecker(Protocol):
    """Waxpeer's ``check-tradelink``: ``None`` when fine, else a reason text."""

    async def check_tradelink(self, url: str) -> str | None:
        """Waxpeer's reason for ``url``, or ``None``."""
        ...


class HoldChecker(Protocol):
    """Steam ``GetTradeHoldDurations``: days a trade would be held; ``None`` = no number."""

    async def trade_hold_days(self, steam_id: str, token: str) -> int | None:
        """Hold in days."""
        ...


def parse_tradelink(raw: str) -> TradeLink:
    """Parse Steam's «Trade URL».

    Raises:
        ValidationError: ``code="trade_link_invalid"`` for anything but that exact link.
    """
    url = raw.strip()
    match = _LINK.match(url)
    if match is None:
        raise ValidationError("not a Steam trade link", code="trade_link_invalid")
    return TradeLink(url=url, partner=int(match.group(1)), token=match.group(2))


def assert_owned(link: TradeLink, steam_id: str) -> None:
    """The link must belong to the signed-in account (spec §7.2).

    Raises:
        ValidationError: ``code="trade_link_not_yours"``.
    """
    if link.steam_id != steam_id:
        raise ValidationError(
            "this trade link belongs to another Steam account", code="trade_link_not_yours"
        )


def _reason_for(info: str) -> Reason:
    text = info.lower()
    if "private" in text:
        return "private"
    if "ban" in text:
        return "trade_ban"
    return "invalid"


def _cache_key(link: TradeLink) -> str:
    return _CACHE_PREFIX + hashlib.sha256(link.url.encode()).hexdigest()[:32]


async def _run(link: TradeLink, *, waxpeer: TradelinkChecker, hold: HoldChecker) -> CheckResult:
    info = await waxpeer.check_tradelink(link.url)
    if info:
        return CheckResult(verdict="bad", reason=_reason_for(info))
    days = await hold.trade_hold_days(link.steam_id, link.token)
    if days:
        return CheckResult(verdict="warn", reason="hold")
    return CheckResult(verdict="ok", reason=None)


async def check_trade_link(
    link: TradeLink, *, waxpeer: TradelinkChecker, hold: HoldChecker, redis: Redis
) -> CheckResult:
    """The advisory check: 10-minute cache per link, 60-second breaker on any failure."""
    unavailable = CheckResult(verdict=None, reason="unavailable")
    key = _cache_key(link)
    with contextlib.suppress(RedisError, ValueError, KeyError, TypeError):
        cached = await redis.get(key)
        if cached is not None:
            data = json.loads(cached)
            return CheckResult(verdict=data["verdict"], reason=data["reason"])
    with contextlib.suppress(RedisError):
        if await redis.exists(BREAKER_KEY):
            return unavailable
    try:
        result = await _run(link, waxpeer=waxpeer, hold=hold)
    except Exception as exc:  # noqa: BLE001 -- advisory: every upstream failure is "unavailable"
        log.warning("users.tradelink.unavailable", error=type(exc).__name__)
        with contextlib.suppress(RedisError):
            await redis.set(BREAKER_KEY, "1", ex=BREAKER_TTL_SECONDS)
        return unavailable
    with contextlib.suppress(RedisError):
        await redis.set(
            key, json.dumps({"verdict": result.verdict, "reason": result.reason}), ex=CACHE_TTL_SECONDS
        )
    log.info("users.tradelink.checked", verdict=result.verdict, reason=result.reason)
    return result
```

Note `ValidationError(..., code=...)`: `AppError.__init__(detail, **extra)` puts `code` into `.extra` and into the problem+json body — that is how the web maps errors to copy.

- [ ] **Step 4: Failing route tests**

```python
# apps/api/tests/integration/test_users_trade_link.py
"""PUT /me/trade-link and POST /me/trade-link/check (Review Focus 2)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio
OWNER = "76561198000000001"
LINK = "https://steamcommunity.com/tradeoffer/new/?partner=39734273&token=AbCdEf12"
OTHER = "https://steamcommunity.com/tradeoffer/new/?partner=39734274&token=AbCdEf12"


async def _auth(c: AsyncClient, steam_id: str = OWNER) -> dict[str, str]:
    r = await c.post("/api/v1/auth/dev-login", json={"steam_id": steam_id})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def test_save_own_link(integration_client: AsyncClient) -> None:
    h = await _auth(integration_client)
    r = await integration_client.put("/api/v1/me/trade-link", json={"url": LINK}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json() == {"trade_link": LINK, "verdict": None, "reason": None, "checked_at": None}
    me = (await integration_client.get("/api/v1/me", headers=h)).json()
    assert me["trade_link"] == LINK


async def test_someone_elses_link_is_refused(integration_client: AsyncClient) -> None:
    h = await _auth(integration_client)
    r = await integration_client.put("/api/v1/me/trade-link", json={"url": OTHER}, headers=h)
    assert r.status_code == 422
    assert r.json()["code"] == "trade_link_not_yours"
    me = (await integration_client.get("/api/v1/me", headers=h)).json()
    assert me["trade_link"] is None


async def test_garbage_is_refused(integration_client: AsyncClient) -> None:
    h = await _auth(integration_client)
    r = await integration_client.put("/api/v1/me/trade-link", json={"url": "hello"}, headers=h)
    assert r.status_code == 422
    assert r.json()["code"] == "trade_link_invalid"


async def test_saving_a_new_link_clears_the_old_verdict(integration_client: AsyncClient, app_overrides) -> None:  # noqa: ANN001
    h = await _auth(integration_client)
    await integration_client.put("/api/v1/me/trade-link", json={"url": LINK}, headers=h)
    app_overrides(hold_days=7)
    r = await integration_client.post("/api/v1/me/trade-link/check", headers=h)
    assert r.json()["verdict"] == "warn"
    assert r.json()["reason"] == "hold"
    assert r.json()["checked_at"] is not None
    link2 = LINK.replace("AbCdEf12", "ZyXwVu98")
    r2 = await integration_client.put("/api/v1/me/trade-link", json={"url": link2}, headers=h)
    assert r2.json()["verdict"] is None and r2.json()["checked_at"] is None


async def test_check_without_keys_is_unavailable_but_link_stays(integration_client: AsyncClient) -> None:
    h = await _auth(integration_client)
    await integration_client.put("/api/v1/me/trade-link", json={"url": LINK}, headers=h)
    r = await integration_client.post("/api/v1/me/trade-link/check", headers=h)
    assert r.status_code == 200
    assert r.json() == {"trade_link": LINK, "verdict": None, "reason": "unavailable", "checked_at": None}


async def test_check_without_a_saved_link_is_422(integration_client: AsyncClient) -> None:
    h = await _auth(integration_client)
    r = await integration_client.post("/api/v1/me/trade-link/check", headers=h)
    assert r.status_code == 422
    assert r.json()["code"] == "trade_link_missing"


async def test_put_replays_by_idempotency_key(integration_client: AsyncClient) -> None:
    h = {**(await _auth(integration_client)), "Idempotency-Key": "k" * 20}
    first = await integration_client.put("/api/v1/me/trade-link", json={"url": LINK}, headers=h)
    second = await integration_client.put(
        "/api/v1/me/trade-link", json={"url": LINK.replace("AbCdEf12", "ZyXwVu98")}, headers=h
    )
    assert second.json() == first.json()


async def test_requires_sign_in(integration_client: AsyncClient) -> None:
    assert (await integration_client.put("/api/v1/me/trade-link", json={"url": LINK})).status_code == 401
```

Add to `apps/api/tests/integration/conftest.py` an `app_overrides` fixture: it reaches the app built by `integration_client` (expose it as `integration_client._transport.app` or, cleaner, refactor `integration_client` to stash `app` on a fixture `integration_app` it depends on) and returns a function `set(hold_days: int | None = 0, waxpeer_info: str | None = None)` that sets `app.dependency_overrides[tradelink_checkers]` to fakes like the unit test's `_Wax`/`_Hold`; clears overrides at teardown.

```python
# apps/api/tests/integration/test_users_routes.py
import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def _auth(c: AsyncClient, **extra: object) -> dict[str, str]:
    r = await c.post("/api/v1/auth/dev-login", json={"steam_id": "76561198000000001", **extra})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def test_me_requires_a_token(integration_client: AsyncClient) -> None:
    assert (await integration_client.get("/api/v1/me")).status_code == 401


async def test_me_shape(integration_client: AsyncClient) -> None:
    h = await _auth(integration_client, display_name="Player", admin=True)
    me = (await integration_client.get("/api/v1/me", headers=h)).json()
    assert me["steam_id"] == "76561198000000001"
    assert me["display_name"] == "Player"
    assert me["locale"] == "ru"
    assert me["roles"] == ["admin"]
    assert me["email"] is None and me["email_verified"] is False
    assert set(me) == {
        "id", "steam_id", "display_name", "avatar_url", "email", "email_verified", "locale",
        "trade_link", "trade_link_verdict", "trade_link_reason", "trade_link_checked_at",
        "roles", "created_at",
    }


async def test_patch_locale_and_email(integration_client: AsyncClient) -> None:
    h = await _auth(integration_client)
    r = await integration_client.patch("/api/v1/me", json={"locale": "uz", "email": "A@Example.uz"}, headers=h)
    assert r.status_code == 200
    assert r.json()["locale"] == "uz"
    assert r.json()["email"] == "A@example.uz"  # EmailStr lower-cases the domain
    assert r.json()["email_verified"] is False


async def test_patch_rejects_bad_values(integration_client: AsyncClient) -> None:
    h = await _auth(integration_client)
    assert (await integration_client.patch("/api/v1/me", json={"locale": "de"}, headers=h)).status_code == 422
    assert (await integration_client.patch("/api/v1/me", json={"email": "nope"}, headers=h)).status_code == 422


async def test_patch_email_null_clears_it(integration_client: AsyncClient) -> None:
    h = await _auth(integration_client)
    await integration_client.patch("/api/v1/me", json={"email": "a@b.uz"}, headers=h)
    r = await integration_client.patch("/api/v1/me", json={"email": None}, headers=h)
    assert r.json()["email"] is None


async def test_banned_account_gets_403_not_401(integration_client: AsyncClient, db_session) -> None:  # noqa: ANN001
    from csmarket.core.clock import now
    from csmarket.modules.users.service import get_user_by_steam_id

    h = await _auth(integration_client)
    user = await get_user_by_steam_id(db_session, "76561198000000001")
    assert user is not None
    user.banned_at = now()
    await db_session.commit()
    r = await integration_client.get("/api/v1/me", headers=h)
    assert r.status_code == 403
    assert r.json()["type"].endswith("/account-suspended")
```

Run → FAIL.

- [ ] **Step 5: Schemas, service, routes**

```python
# apps/api/src/csmarket/modules/users/schemas.py
"""Wire shapes for ``/me``."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from csmarket.modules.users.models import User


class MeOut(BaseModel):
    """The signed-in account as its owner sees it (the trade link is theirs to see)."""

    id: str
    steam_id: str
    display_name: str | None
    avatar_url: str | None
    email: str | None
    email_verified: bool
    locale: Literal["ru", "uz", "en"]
    trade_link: str | None
    trade_link_verdict: Literal["ok", "warn", "bad"] | None
    trade_link_reason: Literal["invalid", "private", "trade_ban", "hold", "unavailable"] | None
    trade_link_checked_at: datetime | None
    roles: list[str]
    created_at: datetime

    @classmethod
    def of(cls, user: User) -> MeOut:
        """Build from the ORM row."""
        return cls(
            id=user.id,
            steam_id=user.steam_id,
            display_name=user.display_name,
            avatar_url=user.avatar_url,
            email=user.email,
            email_verified=user.email_verified_at is not None,
            locale=user.locale,  # type: ignore[arg-type]  # DB check constraint guarantees the set
            trade_link=user.trade_link,
            trade_link_verdict=user.trade_link_verdict,  # type: ignore[arg-type]
            trade_link_reason=user.trade_link_reason,  # type: ignore[arg-type]
            trade_link_checked_at=user.trade_link_checked_at,
            roles=list(user.roles),
            created_at=user.created_at,
        )


class MePatchIn(BaseModel):
    """Editable profile fields; omitted = unchanged, ``email: null`` = clear."""

    model_config = ConfigDict(extra="forbid")

    locale: Literal["ru", "uz", "en"] | None = None
    email: EmailStr | None = None


class TradeLinkIn(BaseModel):
    """A pasted trade link."""

    model_config = ConfigDict(extra="forbid")

    url: str = Field(max_length=300)


class TradeLinkOut(BaseModel):
    """The saved link and its last check."""

    trade_link: str | None
    verdict: Literal["ok", "warn", "bad"] | None
    reason: Literal["invalid", "private", "trade_ban", "hold", "unavailable"] | None
    checked_at: datetime | None

    @classmethod
    def of(cls, user: User) -> TradeLinkOut:
        """Build from the ORM row."""
        return cls(
            trade_link=user.trade_link,
            verdict=user.trade_link_verdict,  # type: ignore[arg-type]
            reason=user.trade_link_reason,  # type: ignore[arg-type]
            checked_at=user.trade_link_checked_at,
        )
```

If mypy accepts the Literal assignments without ignores (it won't — the columns are `str`), keep the comments; prefer `cast()` with a one-line reason if ruff/mypy flag unused ignores.

Service additions (`users/service.py`):

```python
async def update_profile(
    db: AsyncSession, user: User, *, fields: dict[str, object]
) -> None:
    """Apply ``MePatchIn.model_dump(exclude_unset=True)``. Setting an email resets
    verification (ruling P4: verification arrives in M4)."""
    if "locale" in fields and fields["locale"] is not None:
        user.locale = str(fields["locale"])
    if "email" in fields:
        new = fields["email"]
        if new != user.email:
            user.email = None if new is None else str(new)
            user.email_verified_at = None
    user.updated_at = now()
    await db.flush()


async def save_trade_link(db: AsyncSession, user: User, url: str) -> None:
    """Store a parsed, owned link; a new link forgets the previous check."""
    if url != user.trade_link:
        user.trade_link = url
        user.trade_link_verdict = None
        user.trade_link_reason = None
        user.trade_link_checked_at = None
    user.updated_at = now()
    await db.flush()


async def record_trade_link_check(
    db: AsyncSession, user: User, *, verdict: str | None, reason: str | None
) -> None:
    """Persist a check. ``unavailable`` keeps the last real verdict's timestamp off."""
    user.trade_link_verdict = verdict
    user.trade_link_reason = reason
    if verdict is not None:
        user.trade_link_checked_at = now()
    user.updated_at = now()
    await db.flush()
```

```python
# apps/api/src/csmarket/modules/users/routes.py
"""``/api/v1/me`` — the signed-in account, its profile and trade link."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.api.v1.deps import db_session
from csmarket.core.config import get_settings
from csmarket.core.errors import ValidationError
from csmarket.core.idempotency import IDEMPOTENCY_HEADER, load_replay, normalize_idempotency_key, save_replay
from csmarket.core.redis import get_redis
from csmarket.modules.auth.api import current_user, guard_ip, trade_hold_days
from csmarket.modules.skins.api import WaxpeerClient
from csmarket.modules.users.models import User
from csmarket.modules.users.schemas import MeOut, MePatchIn, TradeLinkIn, TradeLinkOut
from csmarket.modules.users.service import record_trade_link_check, save_trade_link, update_profile
from csmarket.modules.users.tradelink import (
    HoldChecker,
    TradelinkChecker,
    assert_owned,
    check_trade_link,
    parse_tradelink,
)

router = APIRouter(prefix="/me", tags=["me"])
_ADVISORY_TIMEOUT = 4.0


class _SteamHold:
    """Steam's hold check with our key; no key → no number (ruling P10)."""

    async def trade_hold_days(self, steam_id: str, token: str) -> int | None:
        key = get_settings().steam_api_key
        if not key:
            return None
        return await trade_hold_days(int(steam_id), token, api_key=key)


def tradelink_checkers() -> tuple[TradelinkChecker, HoldChecker]:
    """Upstream checkers; overridden in tests via ``app.dependency_overrides``."""
    s = get_settings()
    waxpeer = WaxpeerClient(
        api_key=s.waxpeer_api_key, base_url=s.waxpeer_base_url, timeout_seconds=_ADVISORY_TIMEOUT
    )
    return waxpeer, _SteamHold()


async def _replayed(db: AsyncSession, scope: str, key: str | None) -> dict[str, object] | None:
    if key is None:
        return None
    cached = await load_replay(db, scope=scope, idempotency_key=key)
    return cached.body if cached is not None else None


@router.get("", response_model=MeOut, summary="The signed-in account")
async def get_me(user: Annotated[User, Depends(current_user)]) -> MeOut:
    """Profile, roles and trade-link state."""
    return MeOut.of(user)


@router.patch("", response_model=MeOut, summary="Edit locale or email")
async def patch_me(
    body: MePatchIn,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(db_session)],
    idempotency_key: Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)] = None,
) -> MeOut:
    """Partial update; replays a stored response for a repeated ``Idempotency-Key``."""
    key = normalize_idempotency_key(idempotency_key)
    scope = f"users.patch_me:{user.id}"
    if (hit := await _replayed(db, scope, key)) is not None:
        return MeOut.model_validate(hit)
    await update_profile(db, user, fields=body.model_dump(exclude_unset=True))
    out = MeOut.of(user)
    if key is not None:
        await save_replay(db, scope=scope, idempotency_key=key, body=out.model_dump(mode="json"))
    return out


@router.put("/trade-link", response_model=TradeLinkOut, summary="Save my trade link")
async def put_trade_link(
    body: TradeLinkIn,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(db_session)],
    idempotency_key: Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)] = None,
) -> TradeLinkOut:
    """Parse, require that it is this account's own link, save. No external call."""
    key = normalize_idempotency_key(idempotency_key)
    scope = f"users.trade_link:{user.id}"
    if (hit := await _replayed(db, scope, key)) is not None:
        return TradeLinkOut.model_validate(hit)
    link = parse_tradelink(body.url)
    assert_owned(link, user.steam_id)
    await save_trade_link(db, user, link.url)
    out = TradeLinkOut.of(user)
    if key is not None:
        await save_replay(db, scope=scope, idempotency_key=key, body=out.model_dump(mode="json"))
    return out


@router.post("/trade-link/check", response_model=TradeLinkOut, summary="Check my trade link")
async def check_my_trade_link(
    request: Request,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(db_session)],
    checkers: Annotated[tuple[TradelinkChecker, HoldChecker], Depends(tradelink_checkers)],
) -> TradeLinkOut:
    """Advisory check of the saved link (AGENTS §11 carve-out).

    Keyless on purpose: it writes only the derived verdict of a link the user already
    saved, and re-running it is the intended use; the 10-minute cache makes a repeat free.
    """
    await guard_ip(request, bucket="trade-link-check", subject=user.id)
    if not user.trade_link:
        raise ValidationError("no trade link saved", code="trade_link_missing")
    waxpeer, hold = checkers
    result = await check_trade_link(
        parse_tradelink(user.trade_link), waxpeer=waxpeer, hold=hold, redis=get_redis()
    )
    await record_trade_link_check(db, user, verdict=result.verdict, reason=result.reason)
    return TradeLinkOut.of(user)
```

`users/api.py` adds `router`. Mount in `api/v1/__init__.py`. Add `"email-validator>=2.2"` to `apps/api/pyproject.toml` dependencies; `uv lock`.

- [ ] **Step 6: Run, regen schema, README, commit**

```bash
uv sync --all-packages --all-groups
uv run pytest apps/api/tests -n auto -q && uv run ruff check apps && uv run ruff format --check apps && uv run mypy apps && bash scripts/check-no-yupay.sh
cd apps/api && uv run python -m csmarket.scripts.export_openapi ../../docs/api/openapi.json && cd ../..
grep -n "trade-?link" infra/prometheus/alerts/api.yml   # both latency rules already match /me/trade-link/check
```

Update `modules/users/README.md` (HTTP surface, trade-link rules, Redis keys `users:tradelink:{digest}` 600 s / `users:tradelink:breaker` 60 s) and create `modules/skins/README.md` (M1: Waxpeer client only; the key rides the query string; nothing Waxpeer-branded reaches a browser).

```bash
git add -A && git commit -m "feat(api/users): /me, profile edit, trade link with advisory Waxpeer and Steam check

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: `admin` module — role gate, `/admin/me`, `grant_admin` script

**Files:**

- Create: `apps/api/src/csmarket/modules/admin/{__init__,api,deps,routes}.py`, `modules/admin/README.md`, `apps/api/src/csmarket/scripts/grant_admin.py`
- Modify: `api/v1/__init__.py` (mount), `docs/api/openapi.json`
- Test: `apps/api/tests/integration/test_admin_gate.py`, `apps/api/tests/integration/test_grant_admin.py`

**Interfaces:**

- Consumes: `auth.api.current_user`, `users.api.{get_user_by_steam_id, set_roles}`, `users.schemas.MeOut`.
- Produces: `admin.deps.has_role(user, role) -> bool`, `require_admin` dependency (403 `admin role required` for a non-admin, 401 for no token); `GET /api/v1/admin/me` → `MeOut`; `scripts.grant_admin.grant(db, *, steam_id: str, revoke: bool) -> str` returning one of `"granted"`, `"revoked"`, `"unchanged"`, `"not_found"`; CLI `python -m csmarket.scripts.grant_admin --steam-id <id> [--revoke]`.

- [ ] **Step 1: Failing tests**

```python
# apps/api/tests/integration/test_admin_gate.py
import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def _token(c: AsyncClient, *, admin: bool) -> dict[str, str]:
    sid = "76561198000000009" if admin else "76561198000000008"
    r = await c.post("/api/v1/auth/dev-login", json={"steam_id": sid, "admin": admin})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def test_no_token_is_401(integration_client: AsyncClient) -> None:
    assert (await integration_client.get("/api/v1/admin/me")).status_code == 401


async def test_customer_is_403(integration_client: AsyncClient) -> None:
    r = await integration_client.get("/api/v1/admin/me", headers=await _token(integration_client, admin=False))
    assert r.status_code == 403


async def test_admin_gets_their_profile(integration_client: AsyncClient) -> None:
    r = await integration_client.get("/api/v1/admin/me", headers=await _token(integration_client, admin=True))
    assert r.status_code == 200
    assert "admin" in r.json()["roles"]


async def test_role_removal_takes_effect_on_the_next_request(integration_client: AsyncClient, db_session) -> None:  # noqa: ANN001
    from csmarket.modules.users.service import get_user_by_steam_id, set_roles

    h = await _token(integration_client, admin=True)
    user = await get_user_by_steam_id(db_session, "76561198000000009")
    assert user is not None
    await set_roles(db_session, user, [])
    await db_session.commit()
    assert (await integration_client.get("/api/v1/admin/me", headers=h)).status_code == 403
```

```python
# apps/api/tests/integration/test_grant_admin.py
import pytest
from csmarket.modules.users.service import get_user_by_steam_id, upsert_user_by_steam
from csmarket.scripts.grant_admin import grant

pytestmark = pytest.mark.asyncio
SID = "76561198000000010"


async def test_unknown_account_must_sign_in_first(db_session) -> None:  # noqa: ANN001
    assert await grant(db_session, steam_id=SID, revoke=False) == "not_found"


async def test_grant_revoke_and_idempotence(db_session) -> None:  # noqa: ANN001
    await upsert_user_by_steam(db_session, steam_id=SID, display_name=None, avatar_url=None)
    assert await grant(db_session, steam_id=SID, revoke=False) == "granted"
    assert await grant(db_session, steam_id=SID, revoke=False) == "unchanged"
    user = await get_user_by_steam_id(db_session, SID)
    assert user is not None and user.roles == ["admin"]
    assert await grant(db_session, steam_id=SID, revoke=True) == "revoked"
    assert user.roles == []
```

Run → FAIL.

- [ ] **Step 2: Implement**

`admin/deps.py`: copy `yupay:…/modules/admin/deps.py` through the filter (it is already minimal); docstring cites "spec §2.10" instead of ADR-0010. `admin/routes.py`:

```python
"""``/api/v1/admin`` — M1 has only the identity probe the SPA's AuthGuard calls."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from csmarket.modules.admin.deps import require_admin
from csmarket.modules.users.models import User
from csmarket.modules.users.schemas import MeOut

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/me", response_model=MeOut, summary="The signed-in admin")
async def admin_me(user: Annotated[User, Depends(require_admin)]) -> MeOut:
    """200 for an admin, 403 for anyone else signed in, 401 without a token."""
    return MeOut.of(user)
```

`admin/api.py` exports `router`, `require_admin`, `has_role`. Mount.

```python
# apps/api/src/csmarket/scripts/grant_admin.py
"""Grant or revoke the ``admin`` role by Steam ID (ruling P5).

Run inside the api container::

    docker compose exec api python -m csmarket.scripts.grant_admin --steam-id 7656119XXXXXXXXXX
    docker compose exec api python -m csmarket.scripts.grant_admin --steam-id 7656119XXXXXXXXXX --revoke

The account must exist: the person signs in with Steam once first. The script prints
only an outcome word — never the Steam ID — because its output ends up in shell history
and logs.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from csmarket.core.db import dispose_engine, get_session_factory
from csmarket.modules.users.api import get_user_by_steam_id, set_roles

Outcome = Literal["granted", "revoked", "unchanged", "not_found"]


async def grant(db: AsyncSession, *, steam_id: str, revoke: bool) -> Outcome:
    """Add or remove ``admin``; flushes, the caller commits."""
    user = await get_user_by_steam_id(db, steam_id)
    if user is None:
        return "not_found"
    has = "admin" in user.roles
    if revoke and has:
        await set_roles(db, user, [r for r in user.roles if r != "admin"])
        return "revoked"
    if not revoke and not has:
        await set_roles(db, user, [*user.roles, "admin"])
        return "granted"
    return "unchanged"


async def _main(steam_id: str, *, revoke: bool) -> int:
    factory = get_session_factory()
    try:
        async with factory() as db:
            outcome = await grant(db, steam_id=steam_id, revoke=revoke)
            await db.commit()
    finally:
        await dispose_engine()
    print(outcome)
    return 1 if outcome == "not_found" else 0


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--steam-id", required=True, help="steamid64 (17 digits)")
    parser.add_argument("--revoke", action="store_true")
    args = parser.parse_args(argv)
    if not (args.steam_id.isdigit() and len(args.steam_id) == 17):
        print("steam id must be 17 digits", file=sys.stderr)
        return 2
    return asyncio.run(_main(args.steam_id, revoke=args.revoke))


if __name__ == "__main__":
    raise SystemExit(main())
```

The script imports `csmarket.modules.users.api`, which imports `users.models`; `auth.models` must be importable for the FK to resolve — import `csmarket.modules.auth.models` at the top too (`# noqa: F401` with the reason).

- [ ] **Step 3: Run, schema, README, commit**

```bash
uv run pytest apps/api/tests -n auto -q && uv run ruff check apps && uv run ruff format --check apps && uv run mypy apps && bash scripts/check-no-yupay.sh
cd apps/api && uv run python -m csmarket.scripts.export_openapi ../../docs/api/openapi.json && cd ../..
```

`modules/admin/README.md`: role model (`users.roles`, case-sensitive `admin`), 401 vs 403, role changes take effect on the next request, `grant_admin` usage, audit log arrives in M3.

```bash
git add -A && git commit -m "feat(api/admin): admin role gate, /admin/me, grant_admin script

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Scheduler job — purge stale refresh tokens

**Files:**

- Create: `apps/scheduler/src/csmarket_scheduler/jobs/purge_refresh_tokens.py`, `apps/scheduler/tests/test_purge_refresh_tokens.py`, `apps/api/tests/integration/test_auth_purge.py`
- Modify: `apps/scheduler/src/csmarket_scheduler/main.py` (register), `apps/scheduler/src/csmarket_scheduler/jobs/__init__.py` (docstring list), `apps/scheduler/tests/test_main.py` (`test_build_scheduler_is_utc_and_empty_in_m0` → expects exactly `["auth.purge_refresh_tokens"]`)

**Interfaces:**

- Consumes: `auth.service.purge_stale_refresh_tokens(db, *, limit=5000) -> int` (Task 3), `core.db.get_session_factory`, `csmarket_scheduler.startup.first_run_after`.
- Produces: `jobs.purge_refresh_tokens.register(scheduler) -> None` (job id `auth.purge_refresh_tokens`, interval 24 h, first run `first_run_after(300)`), `run() -> int`.

- [ ] **Step 1: Failing tests**

`apps/api/tests/integration/test_auth_purge.py`: port `yupay:apps/api/tests/integration/test_auth_session_purge.py` → rows expired > 7 days ago and rows revoked > 7 days ago are deleted, a fresh and a recently revoked row survive, `limit` bounds one sweep.

```python
# apps/scheduler/tests/test_purge_refresh_tokens.py
from datetime import UTC, datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from csmarket_scheduler.jobs import purge_refresh_tokens


def test_registers_daily_with_an_early_first_run() -> None:
    scheduler = AsyncIOScheduler(timezone="UTC")
    purge_refresh_tokens.register(scheduler)
    (job,) = scheduler.get_jobs()
    assert job.id == "auth.purge_refresh_tokens"
    assert job.trigger.interval == timedelta(hours=24)
    assert job.next_run_time - datetime.now(UTC) <= timedelta(minutes=5)
```

Run → FAIL.

- [ ] **Step 2: Implement**

```python
# apps/scheduler/src/csmarket_scheduler/jobs/purge_refresh_tokens.py
"""Daily: delete refresh tokens that expired or were revoked over 7 days ago."""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from csmarket.core.db import get_session_factory
from csmarket.core.logging import get_logger
from csmarket.modules.auth.service import purge_stale_refresh_tokens

from csmarket_scheduler.startup import first_run_after

log = get_logger("csmarket.scheduler.purge_refresh_tokens")
JOB_ID = "auth.purge_refresh_tokens"


async def run() -> int:
    """One sweep (bounded batch); the next day's sweep continues a backlog."""
    async with get_session_factory()() as db:
        deleted = await purge_stale_refresh_tokens(db)
        await db.commit()
    log.info("auth.refresh_tokens_purged", deleted=deleted)
    return deleted


def register(scheduler: AsyncIOScheduler) -> None:
    """Daily, first run five minutes after boot so restarts can't starve it."""
    scheduler.add_job(
        run,
        "interval",
        hours=24,
        id=JOB_ID,
        next_run_time=first_run_after(300),
        max_instances=1,
        coalesce=True,
    )
```

`main.build_scheduler()` calls `purge_refresh_tokens.register(scheduler)`; import `csmarket.modules.users.models` and `csmarket.modules.auth.models` in `main.py` so the mapper graph resolves (comment why).

- [ ] **Step 3: Run, commit**

```bash
uv run pytest -n auto -q && uv run ruff check apps && uv run ruff format --check apps && uv run mypy apps && bash scripts/check-no-yupay.sh
git add -A && git commit -m "feat(scheduler): daily purge of stale refresh tokens

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

---

### Task 8: Shared session client; storefront sign-in (header, Steam callback, AuthProvider)

**Files:**

- Create: `packages/api-client/src/session.ts`, `packages/api-client/src/session.test.ts`, `packages/api-client/vitest.config.ts`, `apps/web/src/lib/api.ts`, `apps/web/src/lib/auth.tsx`, `apps/web/src/components/Providers.tsx`, `apps/web/src/components/Header.tsx`, `apps/web/src/app/[locale]/auth/steam/callback/page.tsx`, `apps/web/src/app/[locale]/auth/steam/callback/SteamCallback.tsx`, `apps/web/src/test/setup.ts`
- Modify: `packages/api-client/src/index.ts`, `packages/api-client/package.json` (+devDeps `jsdom`, `vitest`), `apps/web/package.json` (+`@tanstack/react-query ^5.59.20`), `apps/web/vitest.config.ts` (`setupFiles`), `apps/web/src/app/[locale]/layout.tsx` (Providers + Header), `packages/i18n/locales/{ru,uz,en}/web.json` (`nav`, `auth`), `pnpm-lock.yaml`
- Test: `packages/api-client/src/session.test.ts`, `apps/web/src/components/Header.test.tsx`

**Interfaces:**

- Produces:
  - `@csmarket/api-client`: `createSessionClient(opts: { baseUrl: string; hintKey: string; lockName: string }) => SessionClient`, where `SessionClient = { api<T>(path, init?), apiGet, apiPost, apiPatch, apiPut, getAccessToken(), setAccessToken(token), clearSession(), hasSessionHint(), refreshAccessToken(): Promise<boolean>, onAuthLost(cb) }`; `SessionApiError(status, statusText, body)` with `.code` (problem+json `code`) and `.type`. `apiPost/apiPut/apiPatch` accept `{ idempotencyKey?: string }` and set `Idempotency-Key`.
  - Web: `apps/web/src/lib/api.ts` exports `session` (a `SessionClient` with `baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8100"`, `hintKey = "csmarket.web.has_session"`, `lockName = "csmarket-web-token-refresh"`) and `API_BASE`; `lib/auth.tsx` exports `AuthProvider`, `useAuth(): { user: Me | null; status: "loading" | "anonymous" | "signed_in" | "suspended"; signInHref(locale): string; completeSteamSignIn(params): Promise<void>; signOut(): Promise<void>; refreshMe(): Promise<void> }` and `type Me` (mirrors `MeOut`).
  - i18n keys `web.nav.{signIn,account}`, `web.auth.callback.{working,failed,retry}`, `web.auth.suspended`.

- [ ] **Step 1: Session client — port and generalise**

Move the logic of `apps/admin/src/lib/api.ts` into `packages/api-client/src/session.ts` as a factory (no module-level state; everything closed over per client): in-memory access token, session-hint flag in `localStorage` under `hintKey` (wrapped in try/catch), single-flight `refreshAccessToken` (Web Locks under `lockName` when available), one replay after a 401, `credentials: "include"` on every call, `POST {baseUrl}/api/v1/auth/logout` fire-and-forget in `clearSession()`, `onAuthLost` callback list fired when refresh returns non-2xx. `api(path, { method, body, anonymous, idempotencyKey })` JSON-encodes `body`. Error type:

```ts
export class SessionApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly statusText: string,
    public readonly body: unknown,
  ) {
    super(`${status.toString()} ${statusText}`);
    this.name = "SessionApiError";
  }

  /** problem+json `code` (e.g. "trade_link_not_yours"), when the API sent one. */
  get code(): string | undefined {
    const b = this.body as { code?: unknown } | null;
    return typeof b?.code === "string" ? b.code : undefined;
  }

  /** problem+json `type` URI. */
  get type(): string | undefined {
    const b = this.body as { type?: unknown } | null;
    return typeof b?.type === "string" ? b.type : undefined;
  }
}
```

`packages/api-client/vitest.config.ts`: `environment: "jsdom"`. Tests:

```ts
// packages/api-client/src/session.test.ts
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createSessionClient, SessionApiError } from "./session";

const BASE = "http://api.test";

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("createSessionClient", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    localStorage.clear();
  });
  afterEach(() => vi.unstubAllGlobals());

  const make = () => createSessionClient({ baseUrl: BASE, hintKey: "hint", lockName: "lock" });

  it("sends the Bearer token and credentials", async () => {
    const c = make();
    c.setAccessToken("A");
    fetchMock.mockResolvedValueOnce(json(200, { ok: true }));
    await c.apiGet("/api/v1/me");
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`${BASE}/api/v1/me`);
    expect(new Headers(init.headers).get("Authorization")).toBe("Bearer A");
    expect(init.credentials).toBe("include");
    expect(localStorage.getItem("hint")).toBe("1");
  });

  it("refreshes once on 401 and replays", async () => {
    const c = make();
    c.setAccessToken("old");
    fetchMock
      .mockResolvedValueOnce(json(401, {}))
      .mockResolvedValueOnce(json(200, { access_token: "new", expires_in: 900 }))
      .mockResolvedValueOnce(json(200, { id: "u" }));
    await expect(c.apiGet<{ id: string }>("/api/v1/me")).resolves.toEqual({ id: "u" });
    expect(c.getAccessToken()).toBe("new");
  });

  it("parallel 401s share one refresh", async () => {
    const c = make();
    c.setAccessToken("old");
    let refreshes = 0;
    fetchMock.mockImplementation((url: string) => {
      if (url.endsWith("/auth/refresh")) {
        refreshes += 1;
        return Promise.resolve(json(200, { access_token: "new", expires_in: 900 }));
      }
      return Promise.resolve(json(c.getAccessToken() === "new" ? 200 : 401, {}));
    });
    await Promise.all([c.apiGet("/a"), c.apiGet("/b"), c.apiGet("/c")]);
    expect(refreshes).toBe(1);
  });

  it("a failed refresh clears the session and fires onAuthLost", async () => {
    const c = make();
    const lost = vi.fn();
    c.onAuthLost(lost);
    c.setAccessToken("old");
    fetchMock
      .mockResolvedValueOnce(json(401, {}))
      .mockResolvedValueOnce(json(401, {}))
      .mockResolvedValue(json(204, {}));
    await expect(c.apiGet("/api/v1/me")).rejects.toBeInstanceOf(SessionApiError);
    expect(lost).toHaveBeenCalledOnce();
    expect(c.getAccessToken()).toBeNull();
    expect(localStorage.getItem("hint")).toBeNull();
  });

  it("exposes problem+json code", async () => {
    const c = make();
    fetchMock.mockResolvedValueOnce(json(422, { code: "trade_link_not_yours", type: "x" }));
    const err = await c
      .apiPut("/api/v1/me/trade-link", { url: "u" }, { idempotencyKey: "k".repeat(20) })
      .catch((e: unknown) => e);
    expect(err).toBeInstanceOf(SessionApiError);
    expect((err as SessionApiError).code).toBe("trade_link_not_yours");
    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(new Headers(init.headers).get("Idempotency-Key")).toBe("k".repeat(20));
  });
});
```

Export from `packages/api-client/src/index.ts`: `createSessionClient`, `SessionApiError`, `type SessionClient`. Keep `createApiClient` untouched. Run `pnpm --filter @csmarket/api-client test` → RED first (module missing), then GREEN.

- [ ] **Step 2: i18n keys (all three locales)**

Add to `packages/i18n/locales/ru/web.json`:

```json
  "nav": { "signIn": "Войти через Steam", "account": "Аккаунт" },
  "auth": {
    "callback": {
      "working": "Входим через Steam…",
      "failed": "Не получилось войти через Steam.",
      "retry": "Попробовать ещё раз"
    },
    "suspended": "Аккаунт заблокирован."
  }
```

`uz/web.json`:

```json
  "nav": { "signIn": "Steam orqali kirish", "account": "Hisob" },
  "auth": {
    "callback": {
      "working": "Steam orqali kiryapmiz…",
      "failed": "Steam orqali kirib boʻlmadi.",
      "retry": "Qayta urinish"
    },
    "suspended": "Hisob bloklangan."
  }
```

`en/web.json`:

```json
  "nav": { "signIn": "Sign in with Steam", "account": "Account" },
  "auth": {
    "callback": {
      "working": "Signing you in with Steam…",
      "failed": "Couldn't sign you in with Steam.",
      "retry": "Try again"
    },
    "suspended": "This account is suspended."
  }
```

The parity test (`packages/i18n`) must stay green.

- [ ] **Step 3: Web client + AuthProvider**

```ts
// apps/web/src/lib/api.ts
import { createSessionClient } from "@csmarket/api-client";

/** Public API origin; inlined at build (NEXT_PUBLIC_*). */
export const API_BASE = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8100").replace(
  /\/$/,
  "",
);

/** One browser session client for the storefront (access token in memory, ruling P2). */
export const session = createSessionClient({
  baseUrl: API_BASE,
  hintKey: "csmarket.web.has_session",
  lockName: "csmarket-web-token-refresh",
});
```

```tsx
// apps/web/src/lib/auth.tsx
"use client";

import { SessionApiError } from "@csmarket/api-client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { API_BASE, session } from "./api";

export interface Me {
  id: string;
  steam_id: string;
  display_name: string | null;
  avatar_url: string | null;
  email: string | null;
  email_verified: boolean;
  locale: "ru" | "uz" | "en";
  trade_link: string | null;
  trade_link_verdict: "ok" | "warn" | "bad" | null;
  trade_link_reason: "invalid" | "private" | "trade_ban" | "hold" | "unavailable" | null;
  trade_link_checked_at: string | null;
  roles: string[];
  created_at: string;
}

type Status = "loading" | "anonymous" | "signed_in" | "suspended";

interface AuthValue {
  user: Me | null;
  status: Status;
  signInHref: (locale: string) => string;
  completeSteamSignIn: (params: Record<string, string>) => Promise<void>;
  signOut: () => Promise<void>;
  refreshMe: () => Promise<void>;
}

const AuthContext = createContext<AuthValue | null>(null);
const ME = ["me"] as const;

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  // The token lives in memory, invisible to the server: stay "loading" until the
  // boot-time refresh settles so server and first client render agree.
  const [booted, setBooted] = useState(false);
  const [hasToken, setHasToken] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      if (!session.getAccessToken() && session.hasSessionHint()) {
        await session.refreshAccessToken();
      }
      if (!cancelled) {
        setHasToken(Boolean(session.getAccessToken()));
        setBooted(true);
      }
    })();
    const off = session.onAuthLost(() => {
      setHasToken(false);
      qc.removeQueries({ queryKey: ME });
    });
    return () => {
      cancelled = true;
      off();
    };
  }, [qc]);

  const me = useQuery({
    queryKey: ME,
    queryFn: () => session.apiGet<Me>("/api/v1/me"),
    enabled: booted && hasToken,
    retry: false,
    staleTime: 60_000,
  });

  const suspended = me.error instanceof SessionApiError && me.error.status === 403;
  const status: Status =
    !booted || (hasToken && me.isPending && !me.error)
      ? "loading"
      : suspended
        ? "suspended"
        : me.data
          ? "signed_in"
          : "anonymous";

  const completeSteamSignIn = useCallback(
    async (params: Record<string, string>) => {
      const tokens = await session.apiPost<{ access_token: string }>(
        "/api/v1/auth/steam",
        { app: "web", params },
        { anonymous: true },
      );
      session.setAccessToken(tokens.access_token);
      setHasToken(true);
      await qc.fetchQuery({ queryKey: ME, queryFn: () => session.apiGet<Me>("/api/v1/me") });
    },
    [qc],
  );

  const signOut = useCallback(async () => {
    session.clearSession();
    setHasToken(false);
    qc.removeQueries({ queryKey: ME });
  }, [qc]);

  const refreshMe = useCallback(async () => {
    await qc.invalidateQueries({ queryKey: ME });
  }, [qc]);

  const value = useMemo<AuthValue>(
    () => ({
      user: me.data ?? null,
      status,
      signInHref: (locale: string) =>
        `${API_BASE}/api/v1/auth/steam/start?app=web&locale=${encodeURIComponent(locale)}`,
      completeSteamSignIn,
      signOut,
      refreshMe,
    }),
    [me.data, status, completeSteamSignIn, signOut, refreshMe],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
```

(If `apiPost`'s third argument shape from Step 1 differs — `{ anonymous?, idempotencyKey? }` — keep these call sites consistent with it.)

```tsx
// apps/web/src/components/Providers.tsx
"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { AuthProvider } from "@/lib/auth";

export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(
    () => new QueryClient({ defaultOptions: { queries: { refetchOnWindowFocus: false } } }),
  );
  return (
    <QueryClientProvider client={client}>
      <AuthProvider>{children}</AuthProvider>
    </QueryClientProvider>
  );
}
```

- [ ] **Step 4: Header (failing test first)**

```tsx
// apps/web/src/components/Header.test.tsx
// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import ru from "@csmarket/i18n/locales/ru/web.json";
import common from "@csmarket/i18n/locales/ru/common.json";

import { Header } from "./Header";

const auth = vi.hoisted(() => ({ value: {} as Record<string, unknown> }));
vi.mock("@/lib/auth", () => ({ useAuth: () => auth.value }));
vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

function renderHeader() {
  return render(
    <NextIntlClientProvider locale="ru" messages={{ web: ru, common }}>
      <Header locale="ru" />
    </NextIntlClientProvider>,
  );
}

describe("Header", () => {
  it("offers Steam sign-in to a visitor", () => {
    auth.value = {
      status: "anonymous",
      user: null,
      signInHref: (l: string) => `http://api/api/v1/auth/steam/start?app=web&locale=${l}`,
    };
    renderHeader();
    const link = screen.getByRole("link", { name: "Войти через Steam" });
    expect(link.getAttribute("href")).toContain("app=web&locale=ru");
  });

  it("links a signed-in user to their account", () => {
    auth.value = {
      status: "signed_in",
      user: { display_name: "Player", avatar_url: null },
      signInHref: () => "",
    };
    renderHeader();
    expect(screen.getByRole("link", { name: /Player/ }).getAttribute("href")).toBe("/account");
  });
});
```

`apps/web/src/test/setup.ts`: `import "@testing-library/jest-dom/vitest";`; add `setupFiles: ["./src/test/setup.ts"]` to `apps/web/vitest.config.ts` (env stays `node` by default; component tests opt into jsdom per file).

```tsx
// apps/web/src/components/Header.tsx
"use client";

import { useTranslations } from "next-intl";

import { Link } from "@/i18n/navigation";
import { useAuth } from "@/lib/auth";

export function Header({ locale }: { locale: string }) {
  const t = useTranslations("web.nav");
  const common = useTranslations("common");
  const { status, user, signInHref } = useAuth();
  return (
    <header className="border-border flex h-14 items-center justify-between border-b px-5">
      <Link href="/" className="font-mono text-sm font-bold uppercase tracking-widest">
        {common("brand")}
      </Link>
      {status === "signed_in" && user ? (
        <Link href="/account" className="flex items-center gap-2 text-sm font-semibold">
          {user.avatar_url ? (
            // Steam CDN avatars; next/image would need remotePatterns per CDN host.
            // eslint-disable-next-line @next/next/no-img-element
            <img src={user.avatar_url} alt="" width={28} height={28} className="rounded-full" />
          ) : null}
          <span>{user.display_name ?? t("account")}</span>
        </Link>
      ) : status === "loading" ? (
        <span aria-hidden className="bg-surface h-8 w-32 animate-pulse rounded-md" />
      ) : (
        <a
          href={signInHref(locale)}
          className="bg-accent text-accent-fg rounded-md px-4 py-2 text-sm font-semibold"
        >
          {t("signIn")}
        </a>
      )}
    </header>
  );
}
```

Wire into `app/[locale]/layout.tsx`: inside `NextIntlClientProvider`, wrap `children` with `<Providers><Header locale={locale} />{children}</Providers>`. The hello page's `<main>` keeps `min-h-screen`; change it to `min-h-[calc(100vh-3.5rem)]` so the header doesn't push it.

- [ ] **Step 5: Steam callback page**

```tsx
// apps/web/src/app/[locale]/auth/steam/callback/page.tsx
import { Suspense } from "react";

import { SteamCallback } from "./SteamCallback";

export const dynamic = "force-dynamic";

export default function SteamCallbackPage() {
  return (
    <Suspense>
      <SteamCallback />
    </Suspense>
  );
}
```

```tsx
// apps/web/src/app/[locale]/auth/steam/callback/SteamCallback.tsx
"use client";

import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";

import { useRouter } from "@/i18n/navigation";
import { routing } from "@/i18n/routing";
import { useAuth } from "@/lib/auth";

/** Steam returns here (ruling P1); we hand the openid.* params to the API. */
export function SteamCallback() {
  const t = useTranslations("web.auth.callback");
  const search = useSearchParams();
  const router = useRouter();
  const { completeSteamSignIn, signInHref } = useAuth();
  const [failed, setFailed] = useState(false);
  const started = useRef(false);
  const requested = search.get("locale") ?? "ru";
  const locale = (routing.locales as readonly string[]).includes(requested) ? requested : "ru";

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    const params: Record<string, string> = {};
    search.forEach((value, key) => {
      if (key.startsWith("openid.")) params[key] = value;
    });
    // The assertion carries the Steam ID; keep it out of history and referrers.
    window.history.replaceState(null, "", window.location.pathname);
    completeSteamSignIn(params)
      .then(() => router.replace("/account", { locale }))
      .catch(() => setFailed(true));
  }, [search, completeSteamSignIn, router, locale]);

  return (
    <main className="mx-auto flex min-h-[60vh] max-w-xl flex-col items-center justify-center px-6 text-center">
      {failed ? (
        <>
          <h1 className="text-xl font-bold">{t("failed")}</h1>
          <a
            href={signInHref(locale)}
            className="bg-accent text-accent-fg mt-6 rounded-md px-5 py-3 font-semibold"
          >
            {t("retry")}
          </a>
        </>
      ) : (
        <p className="text-fg-muted">{t("working")}</p>
      )}
    </main>
  );
}
```

`return_to` is `{web_base_url}/auth/steam/callback?locale=…` — the bare (ru) path; next-intl serves it under `[locale]=ru`, and the page redirects to the visitor's locale.

- [ ] **Step 6: Run, commit**

```bash
pnpm install
pnpm --filter @csmarket/api-client test && pnpm --filter @csmarket/i18n test && pnpm --filter @csmarket/web test
pnpm exec turbo run lint typecheck --filter=@csmarket/web --filter=@csmarket/api-client
NEXT_PUBLIC_API_BASE_URL=http://localhost:8100 pnpm --filter @csmarket/web build
pnpm exec prettier --check . && bash scripts/check-no-yupay.sh
git add -A && git commit -m "feat(web/auth): Steam sign-in header, callback page, shared session client

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Storefront `/account` — profile, trade link with «где взять?», email

**Files:**

- Create: `apps/web/src/app/[locale]/account/page.tsx`, `apps/web/src/components/account/{AccountView,TradeLinkForm,EmailForm}.tsx`, `apps/web/src/lib/trade-link.ts`, `apps/web/src/lib/trade-link.test.ts`, `apps/web/src/components/account/TradeLinkForm.test.tsx`
- Modify: `packages/i18n/locales/{ru,uz,en}/web.json` (`account`)

**Interfaces:**

- Consumes: `useAuth()`, `session` (Task 8), `/api/v1/me` routes (Task 5).
- Produces: `lib/trade-link.ts`: `type CheckState = { verdict: Me["trade_link_verdict"]; reason: Me["trade_link_reason"] }`, `verdictMessage(state): { tone: "ok" | "warn" | "bad" | "muted"; key: string } | null` (keys under `web.account.tradeLink.status.*`), `errorKey(code: string | undefined): string` (keys under `web.account.tradeLink.errors.*`), `STEAM_TRADE_URL_PAGE = "https://steamcommunity.com/my/tradeoffers/privacy#trade_offer_access_url"`.

- [ ] **Step 1: i18n keys**

`ru/web.json` add:

```json
  "account": {
    "title": "Аккаунт",
    "signedOut": "Войдите через Steam, чтобы открыть аккаунт.",
    "signOut": "Выйти",
    "tradeLink": {
      "title": "Ссылка на обмен",
      "hint": "Сюда продавец отправит скин. Ссылку нужно сохранить один раз.",
      "whereToFind": "Где взять?",
      "steps": "В Steam откройте Инвентарь → Предложения обмена → «Кто может отправлять мне предложения обмена?». Скопируйте ссылку из поля «Ссылка на обмен».",
      "openSteam": "Открыть страницу в Steam",
      "save": "Сохранить",
      "saving": "Сохраняем…",
      "check": "Проверить ещё раз",
      "checking": "Проверяем ссылку…",
      "status": {
        "ok": "Ссылка работает — скин придёт сразу.",
        "hold": "Steam задержит обмен: в аккаунте не включён мобильный аутентификатор Steam Guard. Включите его в приложении Steam — тогда скин придёт сразу.",
        "invalid": "Ссылка не работает. Скопируйте её заново в Steam.",
        "private": "Инвентарь скрыт. Откройте его в настройках приватности Steam.",
        "trade_ban": "У аккаунта ограничение на обмен в Steam. Скин на него не придёт.",
        "unavailable": "Сейчас не получилось проверить. Ссылка сохранена — проверим перед покупкой."
      },
      "errors": {
        "trade_link_invalid": "Это не ссылка на обмен Steam. Она начинается с https://steamcommunity.com/tradeoffer/new/",
        "trade_link_not_yours": "Это ссылка другого аккаунта Steam. Нужна ссылка аккаунта, с которым вы вошли.",
        "generic": "Не получилось сохранить. Попробуйте ещё раз."
      }
    },
    "email": {
      "title": "Email",
      "hint": "Для чеков и новостей о заказах. Необязательно.",
      "save": "Сохранить",
      "saved": "Сохранено.",
      "invalid": "Проверьте адрес."
    }
  }
```

`uz/web.json`:

```json
  "account": {
    "title": "Hisob",
    "signedOut": "Hisobni ochish uchun Steam orqali kiring.",
    "signOut": "Chiqish",
    "tradeLink": {
      "title": "Almashuv havolasi",
      "hint": "Sotuvchi skinni shu havolaga yuboradi. Havolani bir marta saqlash kifoya.",
      "whereToFind": "Qayerdan olaman?",
      "steps": "Steamʼda Inventar → Almashuv takliflari → «Menga kim almashuv taklifini yubora oladi?» boʻlimini oching. «Almashuv havolasi» maydonidagi havolani nusxalang.",
      "openSteam": "Steamʼda sahifani ochish",
      "save": "Saqlash",
      "saving": "Saqlanmoqda…",
      "check": "Yana tekshirish",
      "checking": "Havola tekshirilmoqda…",
      "status": {
        "ok": "Havola ishlaydi — skin darhol keladi.",
        "hold": "Steam almashuvni kechiktiradi: hisobda Steam Guard mobil autentifikatori yoqilmagan. Uni Steam ilovasida yoqing — skin darhol keladi.",
        "invalid": "Havola ishlamaydi. Uni Steamʼdan qaytadan nusxalang.",
        "private": "Inventar yashirilgan. Uni Steam maxfiylik sozlamalarida oching.",
        "trade_ban": "Hisobda Steam almashuv cheklovi bor. Skin unga kelmaydi.",
        "unavailable": "Hozir tekshirib boʻlmadi. Havola saqlandi — xariddan oldin tekshiramiz."
      },
      "errors": {
        "trade_link_invalid": "Bu Steam almashuv havolasi emas. U https://steamcommunity.com/tradeoffer/new/ bilan boshlanadi",
        "trade_link_not_yours": "Bu boshqa Steam hisobining havolasi. Siz kirgan hisobning havolasi kerak.",
        "generic": "Saqlab boʻlmadi. Qayta urinib koʻring."
      }
    },
    "email": {
      "title": "Email",
      "hint": "Cheklar va buyurtma xabarlari uchun. Ixtiyoriy.",
      "save": "Saqlash",
      "saved": "Saqlandi.",
      "invalid": "Manzilni tekshiring."
    }
  }
```

`en/web.json`:

```json
  "account": {
    "title": "Account",
    "signedOut": "Sign in with Steam to open your account.",
    "signOut": "Sign out",
    "tradeLink": {
      "title": "Trade link",
      "hint": "The seller sends your skin here. Save it once.",
      "whereToFind": "Where do I find it?",
      "steps": "In Steam open Inventory → Trade Offers → \"Who can send me Trade Offers?\". Copy the link from the \"Trade URL\" field.",
      "openSteam": "Open the page in Steam",
      "save": "Save",
      "saving": "Saving…",
      "check": "Check again",
      "checking": "Checking the link…",
      "status": {
        "ok": "The link works — your skin arrives right away.",
        "hold": "Steam will hold the trade: Steam Guard Mobile Authenticator is off on this account. Turn it on in the Steam app and the skin arrives right away.",
        "invalid": "The link doesn't work. Copy it again from Steam.",
        "private": "Your inventory is private. Make it public in Steam privacy settings.",
        "trade_ban": "This account has a Steam trade restriction. A skin can't be sent to it.",
        "unavailable": "We couldn't check it right now. The link is saved — we'll check before you buy."
      },
      "errors": {
        "trade_link_invalid": "That isn't a Steam trade link. It starts with https://steamcommunity.com/tradeoffer/new/",
        "trade_link_not_yours": "That link belongs to another Steam account. Use the one you signed in with.",
        "generic": "Couldn't save it. Please try again."
      }
    },
    "email": {
      "title": "Email",
      "hint": "For receipts and order updates. Optional.",
      "save": "Save",
      "saved": "Saved.",
      "invalid": "Please check the address."
    }
  }
```

- [ ] **Step 2: Pure helpers — test first**

```ts
// apps/web/src/lib/trade-link.test.ts
import { describe, expect, it } from "vitest";

import { errorKey, verdictMessage } from "./trade-link";

describe("verdictMessage", () => {
  it("maps every state to copy", () => {
    expect(verdictMessage({ verdict: "ok", reason: null })).toEqual({ tone: "ok", key: "ok" });
    expect(verdictMessage({ verdict: "warn", reason: "hold" })).toEqual({
      tone: "warn",
      key: "hold",
    });
    expect(verdictMessage({ verdict: "bad", reason: "private" })).toEqual({
      tone: "bad",
      key: "private",
    });
    expect(verdictMessage({ verdict: "bad", reason: "trade_ban" })).toEqual({
      tone: "bad",
      key: "trade_ban",
    });
    expect(verdictMessage({ verdict: "bad", reason: null })).toEqual({
      tone: "bad",
      key: "invalid",
    });
    expect(verdictMessage({ verdict: null, reason: "unavailable" })).toEqual({
      tone: "muted",
      key: "unavailable",
    });
    expect(verdictMessage({ verdict: null, reason: null })).toBeNull();
  });
});

describe("errorKey", () => {
  it("knows the API codes and falls back", () => {
    expect(errorKey("trade_link_invalid")).toBe("trade_link_invalid");
    expect(errorKey("trade_link_not_yours")).toBe("trade_link_not_yours");
    expect(errorKey("something_else")).toBe("generic");
    expect(errorKey(undefined)).toBe("generic");
  });
});
```

```ts
// apps/web/src/lib/trade-link.ts
import type { Me } from "./auth";

export const STEAM_TRADE_URL_PAGE =
  "https://steamcommunity.com/my/tradeoffers/privacy#trade_offer_access_url";

export interface CheckState {
  verdict: Me["trade_link_verdict"];
  reason: Me["trade_link_reason"];
}

type Tone = "ok" | "warn" | "bad" | "muted";

/** Copy key under `web.account.tradeLink.status`, or null when nothing was checked. */
export function verdictMessage(state: CheckState): { tone: Tone; key: string } | null {
  switch (state.verdict) {
    case "ok":
      return { tone: "ok", key: "ok" };
    case "warn":
      return { tone: "warn", key: "hold" };
    case "bad":
      return {
        tone: "bad",
        key: state.reason === "private" || state.reason === "trade_ban" ? state.reason : "invalid",
      };
    case null:
      return state.reason === "unavailable" ? { tone: "muted", key: "unavailable" } : null;
  }
}

const KNOWN = new Set(["trade_link_invalid", "trade_link_not_yours"]);

/** Copy key under `web.account.tradeLink.errors`. */
export function errorKey(code: string | undefined): string {
  return code && KNOWN.has(code) ? code : "generic";
}
```

- [ ] **Step 3: TradeLinkForm — test first**

```tsx
// apps/web/src/components/account/TradeLinkForm.test.tsx
// @vitest-environment jsdom
import { SessionApiError } from "@csmarket/api-client";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import common from "@csmarket/i18n/locales/ru/common.json";
import ru from "@csmarket/i18n/locales/ru/web.json";

import { TradeLinkForm } from "./TradeLinkForm";

const api = vi.hoisted(() => ({ apiPut: vi.fn(), apiPost: vi.fn() }));
vi.mock("@/lib/api", () => ({ session: api }));
const LINK = "https://steamcommunity.com/tradeoffer/new/?partner=39734273&token=AbCdEf12";

function setup(initial: string | null = null) {
  const onChange = vi.fn();
  render(
    <NextIntlClientProvider locale="ru" messages={{ web: ru, common }}>
      <TradeLinkForm
        initial={{ trade_link: initial, verdict: null, reason: null }}
        onChange={onChange}
      />
    </NextIntlClientProvider>,
  );
  return { onChange };
}

describe("TradeLinkForm", () => {
  beforeEach(() => {
    api.apiPut.mockReset();
    api.apiPost.mockReset();
  });

  it("explains where to find the link", () => {
    setup();
    fireEvent.click(screen.getByText("Где взять?"));
    expect(screen.getByText(/Предложения обмена/)).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Открыть страницу в Steam" }).getAttribute("href"),
    ).toContain("tradeoffers/privacy");
  });

  it("saves with an idempotency key, then checks and shows the verdict", async () => {
    api.apiPut.mockResolvedValue({
      trade_link: LINK,
      verdict: null,
      reason: null,
      checked_at: null,
    });
    api.apiPost.mockResolvedValue({
      trade_link: LINK,
      verdict: "warn",
      reason: "hold",
      checked_at: "2026-10-01T00:00:00Z",
    });
    const { onChange } = setup();
    fireEvent.change(screen.getByRole("textbox"), { target: { value: LINK } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    await waitFor(() => expect(screen.getByText(/Steam задержит обмен/)).toBeInTheDocument());
    const [, body, opts] = api.apiPut.mock.calls[0] as [
      string,
      { url: string },
      { idempotencyKey: string },
    ];
    expect(body.url).toBe(LINK);
    expect(opts.idempotencyKey.length).toBeGreaterThanOrEqual(16);
    expect(api.apiPost).toHaveBeenCalledWith("/api/v1/me/trade-link/check", {});
    expect(onChange).toHaveBeenCalled();
  });

  it("shows the API's reason when the link is someone else's", async () => {
    api.apiPut.mockRejectedValue(
      new SessionApiError(422, "Unprocessable", { code: "trade_link_not_yours" }),
    );
    setup();
    fireEvent.change(screen.getByRole("textbox"), { target: { value: LINK } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    await waitFor(() => expect(screen.getByText(/другого аккаунта Steam/)).toBeInTheDocument());
    expect(api.apiPost).not.toHaveBeenCalled();
  });
});
```

```tsx
// apps/web/src/components/account/TradeLinkForm.tsx
"use client";

import { SessionApiError } from "@csmarket/api-client";
import { Button } from "@csmarket/ui";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { session } from "@/lib/api";
import { errorKey, STEAM_TRADE_URL_PAGE, verdictMessage, type CheckState } from "@/lib/trade-link";

interface TradeLinkState extends CheckState {
  trade_link: string | null;
}

interface TradeLinkOut extends TradeLinkState {
  checked_at: string | null;
}

interface Props {
  initial: TradeLinkState;
  onChange: () => void;
}

const TONE: Record<string, string> = {
  ok: "text-success",
  warn: "text-warning",
  bad: "text-danger",
  muted: "text-fg-muted",
};

export function TradeLinkForm({ initial, onChange }: Props) {
  const t = useTranslations("web.account.tradeLink");
  const [value, setValue] = useState(initial.trade_link ?? "");
  const [state, setState] = useState<CheckState>({
    verdict: initial.verdict,
    reason: initial.reason,
  });
  const [busy, setBusy] = useState<"saving" | "checking" | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function check() {
    setBusy("checking");
    try {
      const out = await session.apiPost<TradeLinkOut>("/api/v1/me/trade-link/check", {});
      setState({ verdict: out.verdict, reason: out.reason });
    } catch {
      setState({ verdict: null, reason: "unavailable" });
    } finally {
      setBusy(null);
      onChange();
    }
  }

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy("saving");
    try {
      const out = await session.apiPut<TradeLinkOut>(
        "/api/v1/me/trade-link",
        { url: value.trim() },
        { idempotencyKey: crypto.randomUUID() },
      );
      setState({ verdict: out.verdict, reason: out.reason });
    } catch (err) {
      setBusy(null);
      setError(errorKey(err instanceof SessionApiError ? err.code : undefined));
      return;
    }
    await check();
  }

  const message = verdictMessage(state);
  return (
    <section className="border-border rounded-lg border p-5">
      <h2 className="text-lg font-bold">{t("title")}</h2>
      <p className="text-fg-muted mt-1 text-sm">{t("hint")}</p>
      <details className="mt-3 text-sm">
        <summary className="text-accent cursor-pointer font-semibold">{t("whereToFind")}</summary>
        <p className="text-fg-muted mt-2">{t("steps")}</p>
        <a
          href={STEAM_TRADE_URL_PAGE}
          target="_blank"
          rel="noreferrer"
          className="text-accent mt-2 inline-block underline"
        >
          {t("openSteam")}
        </a>
      </details>
      <form onSubmit={save} className="mt-4 flex flex-col gap-3 sm:flex-row">
        <input
          type="url"
          inputMode="url"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="https://steamcommunity.com/tradeoffer/new/?partner=…&token=…"
          aria-label={t("title")}
          className="border-border bg-surface flex-1 rounded-md border px-3 py-2 text-sm"
          required
        />
        <Button type="submit" disabled={busy !== null}>
          {busy === "saving" ? t("saving") : t("save")}
        </Button>
      </form>
      {error ? <p className="text-danger mt-3 text-sm">{t(`errors.${error}`)}</p> : null}
      {busy === "checking" ? <p className="text-fg-muted mt-3 text-sm">{t("checking")}</p> : null}
      {busy === null && message ? (
        <p className={`mt-3 text-sm ${TONE[message.tone] ?? ""}`}>{t(`status.${message.key}`)}</p>
      ) : null}
      {busy === null && initial.trade_link && !error ? (
        <button
          type="button"
          onClick={() => void check()}
          className="text-accent mt-2 text-sm underline"
        >
          {t("check")}
        </button>
      ) : null}
    </section>
  );
}
```

`input type="url"` renders role `textbox` in jsdom; if the test's `getByRole("textbox")` misses it, query by label (`getByLabelText("Ссылка на обмен")`) — don't change the input type. If `@csmarket/ui` `Button` isn't resolvable from web tests, it is — `@csmarket/ui` is a web dependency.

- [ ] **Step 4: EmailForm, AccountView, page**

`EmailForm` (`components/account/EmailForm.tsx`): controlled `input type="email"` prefilled with `me.email`, `PATCH /api/v1/me {email: value || null}` with an `idempotencyKey`, shows `saved` / `invalid` (422) copy, calls `onChange`.

```tsx
// apps/web/src/components/account/AccountView.tsx
"use client";

import { Button } from "@csmarket/ui";
import { useTranslations } from "next-intl";

import { EmailForm } from "./EmailForm";
import { TradeLinkForm } from "./TradeLinkForm";

import { useAuth } from "@/lib/auth";

export function AccountView({ locale }: { locale: string }) {
  const t = useTranslations("web.account");
  const auth = useTranslations("web.auth");
  const nav = useTranslations("web.nav");
  const { status, user, signInHref, signOut, refreshMe } = useAuth();

  if (status === "loading") {
    return <div aria-busy className="bg-surface h-40 animate-pulse rounded-lg" />;
  }
  if (status === "suspended") {
    return <p className="text-danger">{auth("suspended")}</p>;
  }
  if (status !== "signed_in" || !user) {
    return (
      <div className="flex flex-col items-start gap-4">
        <p className="text-fg-muted">{t("signedOut")}</p>
        <a
          href={signInHref(locale)}
          className="bg-accent text-accent-fg rounded-md px-5 py-3 font-semibold"
        >
          {nav("signIn")}
        </a>
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center gap-4">
        {user.avatar_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={user.avatar_url} alt="" width={56} height={56} className="rounded-full" />
        ) : null}
        <p className="text-xl font-bold">{user.display_name ?? "Steam"}</p>
      </div>
      <TradeLinkForm
        initial={{
          trade_link: user.trade_link,
          verdict: user.trade_link_verdict,
          reason: user.trade_link_reason,
        }}
        onChange={() => void refreshMe()}
      />
      <EmailForm email={user.email} onChange={() => void refreshMe()} />
      <Button variant="ghost" onClick={() => void signOut()} className="self-start">
        {t("signOut")}
      </Button>
    </div>
  );
}
```

```tsx
// apps/web/src/app/[locale]/account/page.tsx
import { hasLocale } from "next-intl";
import { getTranslations, setRequestLocale } from "next-intl/server";

import { AccountView } from "@/components/account/AccountView";
import { routing } from "@/i18n/routing";

export async function generateMetadata({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "web.account" });
  return { title: t("title"), robots: { index: false, follow: false } };
}

export default async function AccountPage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  // eslint-disable-next-line @typescript-eslint/no-deprecated -- next/root-params needs Next 16; revisit on upgrade
  if (hasLocale(routing.locales, locale)) setRequestLocale(locale);
  const t = await getTranslations("web.account");
  return (
    <main id="main-content" className="mx-auto max-w-2xl px-6 py-10">
      <h1 className="text-2xl font-bold">{t("title")}</h1>
      <div className="mt-6">
        <AccountView locale={locale} />
      </div>
    </main>
  );
}
```

`TradeLinkForm` keys the copy by `useTranslations("web.account.tradeLink")`; tones use `text-success`/`text-warning`/`text-danger` tokens from `@csmarket/config-tailwind` (they exist).

- [ ] **Step 5: Run, commit**

```bash
pnpm --filter @csmarket/i18n test && pnpm --filter @csmarket/web test
pnpm exec turbo run lint typecheck --filter=@csmarket/web
NEXT_PUBLIC_API_BASE_URL=http://localhost:8100 pnpm --filter @csmarket/web build
pnpm exec prettier --check . && bash scripts/check-no-yupay.sh
git add -A && git commit -m "feat(web/account): account page with trade link, where-to-find hint and email

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Admin SPA — Steam login, callback, role gate

**Files:**

- Create: `apps/admin/src/features/auth/{authStore.ts, AuthGuard.tsx, LoginPage.tsx, SteamCallback.tsx, Forbidden.tsx, AuthGuard.test.tsx, LoginPage.test.tsx}`
- Modify: `apps/admin/src/lib/api.ts` (thin wrapper over `createSessionClient`), `apps/admin/src/app/router.tsx`, `apps/admin/src/app/Layout.tsx` (admin name + sign-out), `apps/admin/src/routes/Dashboard.tsx` (copy: «Вход по Steam работает. Разделы появятся дальше.»)

**Interfaces:**

- Consumes: `createSessionClient`, `SessionApiError` (Task 8); `GET /api/v1/admin/me`, `POST /api/v1/auth/steam`, `GET /api/v1/auth/steam/start?app=admin`.
- Produces: `useAuthStore` (zustand): `{ status: "loading" | "anonymous" | "forbidden" | "suspended" | "admin"; me: AdminMe | null; bootstrap(): Promise<void>; completeSteam(params): Promise<void>; signOut(): void }`; `loginHref(): string` = `${apiBase}/api/v1/auth/steam/start?app=admin&locale=ru`.

- [ ] **Step 1: api.ts wrapper**

```ts
// apps/admin/src/lib/api.ts
/**
 * Admin's session client: same mechanics as the storefront (shared
 * `createSessionClient`), its own session hint and refresh lock. Same-origin
 * `/api` in dev (Vite proxy), absolute `VITE_API_BASE_URL` in prod.
 */
import { createSessionClient, SessionApiError } from "@csmarket/api-client";

export const apiBase = import.meta.env.VITE_API_BASE_URL ?? "";

export const session = createSessionClient({
  baseUrl: apiBase,
  hintKey: "csmarket.admin.has_session",
  lockName: "csmarket-admin-token-refresh",
});

export { SessionApiError as ApiError };

/** The one line of an API failure worth showing an operator. */
export function formatApiError(err: SessionApiError): string {
  const body = err.body as { detail?: string; title?: string } | null;
  return body?.detail ?? body?.title ?? err.message;
}
```

Remove the old module-level implementation (it now lives in the package). Nothing else in admin imports the removed names yet — verify with `grep -rn "lib/api" apps/admin/src`.

- [ ] **Step 2: Store + guard — tests first**

```tsx
// apps/admin/src/features/auth/AuthGuard.test.tsx
import { render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AuthGuard } from "./AuthGuard";
import { useAuthStore } from "./authStore";

function renderAt(path: string) {
  const router = createMemoryRouter(
    [
      { path: "/login", element: <p>login page</p> },
      { element: <AuthGuard />, children: [{ path: "/", element: <p>dashboard</p> }] },
    ],
    { initialEntries: [path] },
  );
  render(<RouterProvider router={router} />);
}

describe("AuthGuard", () => {
  beforeEach(() => {
    useAuthStore.setState({ status: "loading", me: null, bootstrap: vi.fn(async () => {}) });
  });

  it("sends anonymous visitors to /login", async () => {
    useAuthStore.setState({ status: "anonymous" });
    renderAt("/");
    expect(await screen.findByText("login page")).toBeInTheDocument();
  });

  it("refuses a signed-in non-admin", async () => {
    useAuthStore.setState({ status: "forbidden" });
    renderAt("/");
    expect(await screen.findByText(/Нет доступа/)).toBeInTheDocument();
  });

  it("lets an admin through", async () => {
    useAuthStore.setState({
      status: "admin",
      me: { id: "u", display_name: "Owner", roles: ["admin"] },
    });
    renderAt("/");
    expect(await screen.findByText("dashboard")).toBeInTheDocument();
  });
});
```

```ts
// apps/admin/src/features/auth/authStore.ts
import { create } from "zustand";

import { apiBase, ApiError, session } from "@/lib/api";

export interface AdminMe {
  id: string;
  display_name: string | null;
  roles: string[];
}

type Status = "loading" | "anonymous" | "forbidden" | "suspended" | "admin";

interface AuthState {
  status: Status;
  me: AdminMe | null;
  bootstrap: () => Promise<void>;
  completeSteam: (params: Record<string, string>) => Promise<void>;
  signOut: () => void;
}

export function loginHref(): string {
  return `${apiBase}/api/v1/auth/steam/start?app=admin&locale=ru`;
}

async function probe(): Promise<Pick<AuthState, "status" | "me">> {
  if (!session.getAccessToken()) return { status: "anonymous", me: null };
  try {
    const me = await session.apiGet<AdminMe>("/api/v1/admin/me");
    return { status: "admin", me };
  } catch (err) {
    if (err instanceof ApiError && err.status === 403) {
      const suspended = err.type?.endsWith("/account-suspended") ?? false;
      return { status: suspended ? "suspended" : "forbidden", me: null };
    }
    return { status: "anonymous", me: null };
  }
}

export const useAuthStore = create<AuthState>((set) => ({
  status: "loading",
  me: null,
  bootstrap: async () => {
    if (!session.getAccessToken() && session.hasSessionHint()) {
      await session.refreshAccessToken();
    }
    set(await probe());
  },
  completeSteam: async (params) => {
    const tokens = await session.apiPost<{ access_token: string }>(
      "/api/v1/auth/steam",
      { app: "admin", params },
      { anonymous: true },
    );
    session.setAccessToken(tokens.access_token);
    set(await probe());
  },
  signOut: () => {
    session.clearSession();
    set({ status: "anonymous", me: null });
  },
}));
```

```tsx
// apps/admin/src/features/auth/AuthGuard.tsx
import { useEffect } from "react";
import { Navigate, Outlet } from "react-router-dom";

import { useAuthStore } from "./authStore";
import { Forbidden } from "./Forbidden";

export function AuthGuard() {
  const status = useAuthStore((s) => s.status);
  const bootstrap = useAuthStore((s) => s.bootstrap);
  useEffect(() => {
    if (status === "loading") void bootstrap();
  }, [status, bootstrap]);

  if (status === "loading") return <p className="text-fg-muted p-8">Загрузка…</p>;
  if (status === "anonymous") return <Navigate to="/login" replace />;
  if (status === "forbidden" || status === "suspended")
    return <Forbidden suspended={status === "suspended"} />;
  return <Outlet />;
}
```

```tsx
// apps/admin/src/features/auth/Forbidden.tsx
import { Button } from "@csmarket/ui";

import { useAuthStore } from "./authStore";

export function Forbidden({ suspended }: { suspended: boolean }) {
  const signOut = useAuthStore((s) => s.signOut);
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center gap-4 text-center">
      <h1 className="text-2xl font-bold">Нет доступа</h1>
      <p className="text-fg-muted">
        {suspended ? "Этот аккаунт заблокирован." : "Этот аккаунт Steam не администратор."}
      </p>
      <Button variant="secondary" onClick={signOut}>
        Выйти
      </Button>
    </div>
  );
}
```

- [ ] **Step 3: Login + callback pages**

```tsx
// apps/admin/src/features/auth/LoginPage.test.tsx
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { LoginPage } from "./LoginPage";

describe("LoginPage", () => {
  it("starts the admin Steam flow", () => {
    render(
      <MemoryRouter>
        <LoginPage />
      </MemoryRouter>,
    );
    const link = screen.getByRole("link", { name: "Войти через Steam" });
    expect(link.getAttribute("href")).toBe("/api/v1/auth/steam/start?app=admin&locale=ru");
  });
});
```

```tsx
// apps/admin/src/features/auth/LoginPage.tsx
import { loginHref } from "./authStore";

export function LoginPage() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-6 px-6 text-center">
      <p className="font-mono text-sm font-bold uppercase tracking-widest">csmarket admin</p>
      <a href={loginHref()} className="bg-accent text-accent-fg rounded-md px-5 py-3 font-semibold">
        Войти через Steam
      </a>
      <p className="text-fg-muted max-w-sm text-sm">
        Доступ есть у аккаунтов Steam с ролью администратора.
      </p>
    </div>
  );
}
```

```tsx
// apps/admin/src/features/auth/SteamCallback.tsx
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { loginHref, useAuthStore } from "./authStore";

export function SteamCallback() {
  const [search] = useSearchParams();
  const navigate = useNavigate();
  const completeSteam = useAuthStore((s) => s.completeSteam);
  const [failed, setFailed] = useState(false);
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    const params: Record<string, string> = {};
    search.forEach((value, key) => {
      if (key.startsWith("openid.")) params[key] = value;
    });
    window.history.replaceState(null, "", window.location.pathname);
    completeSteam(params)
      .then(() => navigate("/", { replace: true }))
      .catch(() => setFailed(true));
  }, [search, completeSteam, navigate]);

  if (!failed) return <p className="text-fg-muted p-8">Входим через Steam…</p>;
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center gap-4">
      <p className="font-semibold">Не получилось войти через Steam.</p>
      <a href={loginHref()} className="text-accent underline">
        Попробовать ещё раз
      </a>
      <Link to="/login" className="text-fg-muted text-sm">
        Назад
      </Link>
    </div>
  );
}
```

Router:

```tsx
export const router = createBrowserRouter([
  { path: "/login", element: <LoginPage /> },
  { path: "/auth/steam/callback", element: <SteamCallback /> },
  {
    element: <AuthGuard />,
    children: [
      {
        element: <Layout />,
        children: [
          { path: "/", element: <DashboardPage /> },
          { path: "*", element: <NotFoundPage /> },
        ],
      },
    ],
  },
]);
```

`Layout` topbar: right side shows `me.display_name` and a ghost «Выйти» button (`useAuthStore().signOut`). The admin UI copy is Russian (owner-facing), «вы».

- [ ] **Step 4: Run, commit**

```bash
pnpm --filter @csmarket/admin test && pnpm --filter @csmarket/admin lint && pnpm --filter @csmarket/admin typecheck
VITE_API_BASE_URL=http://localhost:8100 pnpm --filter @csmarket/admin build
pnpm exec prettier --check . && bash scripts/check-no-yupay.sh
git add -A && git commit -m "feat(admin/auth): Steam login, callback route and admin role gate

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: e2e — sign-in, account, trade link, admin gate (dev stack)

**Files:**

- Create: `e2e/tests/auth.spec.ts`, `e2e/tests/admin.spec.ts`, `e2e/tests/helpers.ts`
- Modify: `e2e/playwright.config.ts` (projects), `e2e/README.md`

**Interfaces:**

- Consumes: dev stack (R12 ports) with `CSMARKET_DEV_LOGIN_ENABLED=true` (Task 1 compose default); `POST http://localhost:8100/api/v1/auth/dev-login`.
- Produces: projects `web-chromium`, `web-iphone` (baseURL `WEB_BASE_URL ?? http://localhost:3100`, testMatch `home|auth`), `admin-chromium` (baseURL `ADMIN_BASE_URL ?? http://localhost:3102`, testMatch `admin`); env `API_BASE_URL ?? http://localhost:8100`.

- [ ] **Step 1: Helpers + specs**

```ts
// e2e/tests/helpers.ts
import type { Page } from "@playwright/test";

export const API = process.env["API_BASE_URL"] ?? "http://localhost:8100";

/**
 * Dev-only sign-in (ruling P6). Sets the refresh cookie in the browser context and
 * the apps' session hints — without a hint the apps skip the boot-time refresh, the
 * way a real Steam sign-in would have set it.
 */
export async function devLogin(
  page: Page,
  opts: { steamId: string; name?: string; admin?: boolean },
): Promise<void> {
  const r = await page.context().request.post(`${API}/api/v1/auth/dev-login`, {
    data: { steam_id: opts.steamId, display_name: opts.name ?? null, admin: opts.admin ?? false },
  });
  if (!r.ok()) throw new Error(`dev-login ${r.status().toString()}`);
  await page.addInitScript(() => {
    localStorage.setItem("csmarket.web.has_session", "1");
    localStorage.setItem("csmarket.admin.has_session", "1");
  });
}

/** steamid64 → a matching fake trade link (redrawn token, never a real one). */
export function tradeLinkFor(steamId: string, token = "E2eTok12"): string {
  const partner = (BigInt(steamId) - 76561197960265728n).toString();
  return `https://steamcommunity.com/tradeoffer/new/?partner=${partner}&token=${token}`;
}
```

```ts
// e2e/tests/auth.spec.ts
import { expect, test } from "@playwright/test";

import { devLogin, tradeLinkFor } from "./helpers";

test("a visitor sees Steam sign-in pointing at the API", async ({ page }) => {
  await page.goto("/");
  const link = page.getByRole("link", { name: "Войти через Steam" });
  await expect(link).toHaveAttribute("href", /\/api\/v1\/auth\/steam\/start\?app=web&locale=ru$/);
});

test("signed in: account, trade link save and check, sign out", async ({ page }) => {
  const steamId = `7656119800000${String(Date.now()).slice(-4)}`;
  await devLogin(page, { steamId, name: "E2E Player" });
  await page.goto("/account");
  await expect(page.getByText("E2E Player").first()).toBeVisible();

  await page.getByText("Где взять?").click();
  await expect(page.getByRole("link", { name: "Открыть страницу в Steam" })).toBeVisible();

  await page.getByLabel("Ссылка на обмен").fill(tradeLinkFor(steamId));
  await page.getByRole("button", { name: "Сохранить" }).first().click();
  // No Waxpeer/Steam keys in dev: the check is advisory and says so.
  await expect(page.getByText(/Сейчас не получилось проверить/)).toBeVisible();

  await page.reload();
  await expect(page.getByLabel("Ссылка на обмен")).toHaveValue(tradeLinkFor(steamId));

  await page.getByRole("button", { name: "Выйти" }).click();
  await expect(page.getByRole("link", { name: "Войти через Steam" }).first()).toBeVisible();
});

test("someone else's trade link is refused with a reason", async ({ page }) => {
  const steamId = "76561198000000777";
  await devLogin(page, { steamId });
  await page.goto("/account");
  await page.getByLabel("Ссылка на обмен").fill(tradeLinkFor("76561198000000778"));
  await page.getByRole("button", { name: "Сохранить" }).first().click();
  await expect(page.getByText(/ссылка другого аккаунта Steam/)).toBeVisible();
});

test("account page asks a visitor to sign in", async ({ page }) => {
  await page.goto("/en/account");
  await expect(page.getByText("Sign in with Steam to open your account.")).toBeVisible();
});
```

```ts
// e2e/tests/admin.spec.ts
import { expect, test } from "@playwright/test";

import { devLogin } from "./helpers";

test("anonymous goes to the Steam login page", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("link", { name: "Войти через Steam" })).toHaveAttribute(
    "href",
    /\/api\/v1\/auth\/steam\/start\?app=admin&locale=ru$/,
  );
});

test("a customer is refused", async ({ page }) => {
  await devLogin(page, { steamId: "76561198000000880" });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Нет доступа" })).toBeVisible();
});

test("an admin gets in", async ({ page }) => {
  await devLogin(page, { steamId: "76561198000000881", name: "Owner", admin: true });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Дашборд" })).toBeVisible();
  await expect(page.getByText("Owner")).toBeVisible();
});
```

Session hint: both apps refresh on boot only when their `localStorage` hint is set (Task 8), so the helper sets it with `addInitScript` — skipping it makes every signed-in test see a visitor. Cookies: `dev-login` on `localhost:8100` sets a host-only cookie for `localhost`, which the browser sends to `localhost:8100` from the web (3100) and through the admin's Vite proxy (3102) alike — ports don't scope cookies.

Playwright config projects:

```ts
  projects: [
    { name: "web-chromium", testMatch: /(home|auth)\.spec\.ts/, use: { ...devices["Desktop Chrome"], baseURL: WEB } },
    { name: "web-iphone", testMatch: /home\.spec\.ts/, use: { ...devices["iPhone 14"], baseURL: WEB } },
    { name: "admin-chromium", testMatch: /admin\.spec\.ts/, use: { ...devices["Desktop Chrome"], baseURL: ADMIN } },
  ],
```

with `const WEB = process.env["WEB_BASE_URL"] ?? "http://localhost:3100"; const ADMIN = process.env["ADMIN_BASE_URL"] ?? "http://localhost:3102";`.

- [ ] **Step 2: Run against the dev stack**

```bash
docker compose up -d --build
docker compose exec api alembic upgrade head
until curl -sf http://127.0.0.1:8100/readyz >/dev/null; do sleep 2; done
until curl -sf -o /dev/null http://127.0.0.1:3100/; do sleep 3; done
make test-e2e
docker compose down
```

Expected: all specs pass (home 5×2 + auth 4 + admin 3). Never touch `yupay*` containers.

- [ ] **Step 3: Commit**

```bash
pnpm exec prettier --check . && pnpm --filter @csmarket/e2e lint && pnpm --filter @csmarket/e2e typecheck
git add -A && git commit -m "test(e2e): Steam sign-in via dev login, account trade link, admin gate

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12: Docs, ADR-0004, runbook, AGENTS; full verification

**Files:**

- Create: `docs/decisions/0004-steam-auth-and-sessions.md`, `docs/architecture/cache-keys.md`, `docs/runbooks/admin-bootstrap.md`
- Modify: `docs/architecture/module-map.md`, `docs/security/pii-handling.md`, `docs/onboarding/local-setup.md`, `docs/api/README.md`, `AGENTS.md` (§0 table + handoff bullet, §13 dev-login/grant-admin lines), `infra/secrets-example/README.md` (JWT key generation section updated for `CSMARKET_` names)

- [ ] **Step 1: Write the docs**

- **ADR-0004** (MADR template): context (Steam OpenID 2.0 is the only door; spec §7.1); decision = rulings P1, P2, P6, P7, P8 with one paragraph each; consequences (one cookie for web+admin; access tokens die on API restart in dev; dev-login must stay prod-off — test `test_prod_never_exposes_dev_login`); alternatives (API-side callback; access token in a cookie + CSRF tokens).
- **cache-keys.md**: table — key, TTL, writer, reader, contains PII? — rows: `auth:revoked:{jti}` (≤ 900 s), `auth:revoked_sid:{sid}` (900 s), `auth:ipguard:{bucket}:{ip_hash}` and `…:s:{subject_digest}` (window, 60 s), `users:tradelink:{sha256(link)[:32]}` (600 s, value = verdict+reason only), `users:tradelink:breaker` (60 s). Note: no raw IP, Steam ID, token or link in any key.
- **module-map.md**: mark `auth`, `users`, `admin` (gate only) as built in M1, `skins` as "client only (M1), catalogue M2".
- **pii-handling.md**: `users.steam_id` (identity; never logged — redactor key + stem `steamid`), `users.email` (optional, unverified until M4), `users.trade_link` (token = credential; returned only to its owner; never logged; Redis key is a digest), IPs (only as `hash_short` inside `ip_guard` keys, ≤ 60 s), OpenID callback params stripped from the browser URL after sign-in.
- **admin-bootstrap.md**: sign in at `https://admin.csmarket.uz` once with the owner's Steam account (gets "Нет доступа") → `IMAGE_TAG` already in `.env` → `docker compose -f docker-compose.prod.yml exec api python -m csmarket.scripts.grant_admin --steam-id <17 digits>` → prints `granted` → reload the admin. Revoke with `--revoke`. Locally: same with `docker compose exec api …`, or dev-login with `admin: true`.
- **local-setup.md**: "Signing in locally" — real Steam works on localhost (no key needed; persona stays empty without `CSMARKET_STEAM_API_KEY`); dev login via `curl -c` example or e2e helper; how to make yourself admin.
- **docs/api/README.md**: auth section — Bearer access token (15 min) from `/auth/steam`, `/auth/refresh` (cookie `csmarket_refresh`), errors `401` vs `403 account-suspended`, `trade_link_*` codes.
- **AGENTS.md**: §0 table M1 row → plan path `docs/superpowers/plans/2026-10-01-m1-auth-users.md`; handoff bullet "M1 merged on main; next: M2 plan when the owner asks"; §13 add `docker compose exec api python -m csmarket.scripts.grant_admin --steam-id …` and the dev-login note (dev only, prod 404).

- [ ] **Step 2: Full gate**

```bash
git status --porcelain                                   # clean before
make lint typecheck test                                  # ruff, mypy, check-no-yupay, eslint, prettier, tsc, pytest -n auto, vitest
cd apps/api && uv run python -m csmarket.scripts.export_openapi /tmp/o.json && cd ../.. && diff -q /tmp/o.json docs/api/openapi.json
docker compose build && docker compose up -d && docker compose exec api alembic upgrade head
make test-e2e && docker compose down
git status --porcelain                                   # clean after
```

Expected: everything green; pytest output has no warnings; the regenerated schema matches the committed one.

- [ ] **Step 3: Commit**

```bash
pnpm exec prettier --check .
git add -A && git commit -m "docs: ADR-0004 Steam auth and sessions, cache keys, PII, admin bootstrap, AGENTS M1

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Self-review (done while writing)

**Spec coverage (M1 row: "a user signs in and saves a trade link; an admin steam_id opens the admin"):** Steam sign-in → Tasks 3, 4, 8; users + roles → Tasks 2, 6; account page → Task 9; trade link + advisory checks → Task 5, 9; admin shell with role gate → Tasks 6, 10; e2e (spec §14 "sign-in (mocked Steam)") → Task 11. Spec §5 `users` + `refresh_tokens` → Task 2 (+P3 column). §7.1 ip_guard on sign-in → Task 4; §7.2 cache 10 min keyed by hash, token never logged, `warn` on escrow → Task 5. §13 idempotency on writes → Task 5 (`PATCH /me`, `PUT /me/trade-link`), keyless rationale in docstrings for `/auth/steam`, `/auth/refresh`, `/me/trade-link/check`. §11 copy in three locales → Tasks 8, 9. Deviations recorded as rulings P1–P10 and ADR-0004.

**Placeholder scan:** no TBD/TODO. Port steps name the source file and every delta.

**Type consistency:** `steam_id` is `str` everywhere it is stored or compared (`users.steam_id`, `TradeLink.steam_id`, `DevLoginIn.steam_id`, `get_user_by_steam_id`), `int` only inside `auth.steam` (OpenID parse, Steam Web API calls) — `steam_login` converts with `str(steam_id)`, `_SteamHold` with `int(steam_id)`. `TradeLinkOut` fields (`trade_link, verdict, reason, checked_at`) match the web `TradeLinkOut` interface and the tests. `MeOut` field set matches `Me` in `lib/auth.tsx` and `test_me_shape`. Cookie name `csmarket_refresh` in cookies.py, route tests and e2e. Redis keys match cache-keys.md. `SessionClient` method names (`apiGet/apiPost/apiPut/apiPatch`, `setAccessToken`, `clearSession`, `hasSessionHint`, `refreshAccessToken`, `onAuthLost`, `getAccessToken`) consistent across api-client, web and admin; `apiPost/apiPut` third arg `{ anonymous?, idempotencyKey? }`.

**Review Focus → tests:** 1 → Task 4 `test_auth_steam.py` (foreign return_to, admin-vs-web, non-Steam claimed_id, is_valid:false); 2 → Task 5 `test_someone_elses_link_is_refused` + e2e; 3 → Task 3 reuse + ported race test; 4 → Task 3 ban test + Task 5 `test_banned_account_gets_403_not_401` + admin `Forbidden(suspended)`; 5 → Task 4 `test_prod_never_exposes_dev_login`.
