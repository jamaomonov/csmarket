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
- **Trade link:** the link and its advisory verdict live on `users` (added by Task 5 of M1).
- **PII:** never log `steam_id`, email or the trade link (`docs/security/pii-handling.md`).
