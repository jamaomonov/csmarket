# users

Owns the `users` table: one row per customer, keyed by `steam_id` (steamid64 as text).
Steam is the only identity; roles (`admin`) live in `users.roles`.

- **Public interface:** `users.api` — `User`, `STEAM64_BASE`, `get_user_by_id`,
  `get_user_by_steam_id`, `upsert_user_by_steam`, `set_roles`. Other modules import
  nothing else from here.
- **Sign-in upsert:** `upsert_user_by_steam` finds or creates the account and refreshes the
  profile; a concurrent first sign-in loses the INSERT race inside a SAVEPOINT and continues
  as the existing account. Services flush, never commit.
- **Profile guards:** `identity_guard` drops over-long avatar URLs and truncates names
  before they reach an INSERT.
- **HTTP surface** (`routes.py`, mounted from `api/v1/router.py` — not re-exported by
  `users.api`, which `auth` imports; that would close an import cycle):

  | Route                              | Does                                                     |
  | ---------------------------------- | -------------------------------------------------------- |
  | `GET /api/v1/me`                   | `MeOut`: profile, roles, trade link and its last verdict |
  | `PATCH /api/v1/me`                 | `locale`, `email` (omitted = unchanged, `null` = clear)  |
  | `PUT /api/v1/me/trade-link`        | parse, require ownership, save; no external call         |
  | `POST /api/v1/me/trade-link/check` | advisory Waxpeer + Steam check of the saved link         |

  `PATCH` and `PUT` accept `Idempotency-Key` (≥ 16 chars) and replay through
  `core.idempotency` (scopes `users.patch_me:{user_id}`, `users.trade_link:{user_id}`).
  The check is keyless (it writes only a derived verdict; re-running it is the point) and
  sits behind `ip_guard` bucket `trade-link-check`, keyed by IP and user id. It commits
  the read transaction before calling Waxpeer and Steam, so no pooled connection is held
  across the upstream calls (AGENTS §11); the verdict is written in a fresh one.

- **Email (ruling P4, M4b R7):** optional, stored lower-domain via `EmailStr`; any change
  resets `email_verified_at` and queues a confirmation letter (`email_flow.send_verification`,
  60 s cooldown in Redis `users:email_verify:cooldown:{user_id}`). The link's token
  (`email_verify`) is `user_id | email | expiry` sealed with SecretBox, 24 h.
  `POST /me/email/verification` re-sends; `POST /email/confirm` (anonymous, idempotent;
  `routes_email`) confirms while the account's email is still the token's. `MeOut` carries
  `email_verification_sent_at`. Order letters go only to a confirmed address (ADR-0008).
- **Trade link** (`tradelink.py`, spec §7.2):
  - Only `https://steamcommunity.com/tradeoffer/new/?partner=<digits>&token=<6-16 chars>`
    parses (`422 trade_link_invalid` otherwise). ASCII only (`re.ASCII`): look-alike
    Unicode digits or letters are refused.
  - `partner + STEAM64_BASE` must equal the signed-in `steam_id`, or
    `422 trade_link_not_yours` and nothing is written.
  - Saving a different link clears `trade_link_verdict`, `trade_link_reason` and
    `trade_link_checked_at`.
  - The check asks Waxpeer `check-tradelink` (reason text → `private`, `trade_ban` or
    `invalid`, verdict `bad`), then Steam `GetTradeHoldDurations` (non-zero hold → `bad`,
    `hold`: a hold is refused, owner 2026-10-01; `warn` stays in the schema and the DB check
    but nothing produces it). No Steam key → the hold check is skipped (ruling P10).
  - Any upstream failure or a missing Waxpeer key → verdict `null`, reason `unavailable`,
    the link stays saved and `trade_link_checked_at` is not touched; a 60 s breaker stops
    further upstream calls.
  - 4 s timeouts on both calls (AGENTS §11 carve-out).
- **Redis keys:** `users:tradelink:{sha256(link)[:32]}` — 600 s, value is
  `{verdict, reason}` only; `users:tradelink:breaker` — 60 s. No key holds a raw link,
  token, partner or Steam ID.
- **PII:** never log `steam_id`, email or the trade link — its `token` is a credential, and
  `httpx` error text carries it in the URL, so only the exception type name is logged
  (`docs/security/pii-handling.md`). The link is returned only to its owner.
