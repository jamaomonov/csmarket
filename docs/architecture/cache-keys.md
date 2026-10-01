# Redis cache keys

Every Redis key the app writes is listed here, one row per key (`AGENTS.md` § 5). A new key
lands in the same change as its code.

**No key holds a raw IP, Steam ID, email, trade link or token.** Identifiers are hashed
before they go into a key: `hash_short()` (12 hex characters) for an IP, a SHA-256 prefix
(32 hex characters) for a subject or a link. A key is not a log, but `MONITOR` and `SCAN`
read it, so the rule is the same as for logs (`docs/security/pii-handling.md`).

| Key                                                               | TTL                                           | Written by                                                                           | Read by                                                   | PII?                                                                   |
| ----------------------------------------------------------------- | --------------------------------------------- | ------------------------------------------------------------------------------------ | --------------------------------------------------------- | ---------------------------------------------------------------------- |
| `auth:revoked:{jti}`                                              | the access token's remaining life (≤ 900 s)   | `auth.service.logout` (a Bearer on sign-out)                                         | `auth.service` on every authenticated request             | No: `jti` is a random token id                                         |
| `auth:revoked_sid:{sid}`                                          | 900 s (`jwt_access_ttl_seconds`)              | `auth.service` when a session is revoked                                             | `auth.service` on every authenticated request             | No: `sid` is a random session id                                       |
| `auth:ipguard:{bucket}:{hash_short(ip)}`                          | window, 60 s (`auth_ip_guard_window_seconds`) | `auth.ip_guard.guard_ip`                                                             | `auth.ip_guard.guard_ip` (INCR + EXPIRE NX, then compare) | Digest of the IP only; the raw IP is never stored                      |
| `auth:ipguard:{bucket}:{hash_short(ip)}:s:{sha256(subject)[:32]}` | window, 60 s                                  | `auth.ip_guard.guard_ip` when a `subject` is given                                   | `auth.ip_guard.guard_ip`                                  | Digests only (IP, and the subject: the user id for `trade-link-check`) |
| `users:tradelink:{sha256(link)[:32]}`                             | 600 s                                         | `users.tradelink.check_trade_link`                                                   | `users.tradelink.check_trade_link`                        | Value is `{verdict, reason}` only; the key is a digest of the link     |
| `users:tradelink:breaker`                                         | 60 s                                          | `users.tradelink.check_trade_link` on any upstream failure                           | `users.tradelink.check_trade_link`                        | No                                                                     |
| `skins:pricing`                                                   | 3600 s                                        | `skins.settings.load_rules` (on a miss), `publish_rules`                             | `skins.settings.load_rules`                               | No: the pricing rules document                                         |
| `fx:usd_uzs`                                                      | 86 400 s                                      | `fx.service.refresh_usd_uzs` (scheduler `fx.refresh`), `current_usd_uzs` (on a miss) | `fx.service.current_usd_uzs`                              | No: the rate, snapshot id, fetch time and source                       |
| `skins:job:{import\|price_sync}`                                  | none (overwritten each run)                   | `skins.job_status.record_job` (scheduler `skins.catalog_import`, price sync)         | `skins.job_status.read_job` (admin status card)           | No: finished_at, ok, counters, our own error label                     |

## Notes

- **Buckets** in use: `steam-login`, `dev-login` (sign-in routes, no subject) and
  `trade-link-check` (IP plus user id). Per-bucket ceilings: `auth_ip_guard_bucket_max`
  (60 per window each); the subject ceiling is `auth_ip_guard_subject_max` (10).
- **Fail open.** A Redis error in a blocklist read or write, or in `guard_ip`, lets the
  request through; a cache error in the trade-link check falls through to a live check. An
  unwritten `auth:revoked*` marker costs only the acceleration: the session row is revoked
  in Postgres regardless, and the access token expires within its 15 minutes. Logged as
  `auth.blocklist_unwritable` with the blocklist kind, never the key.
- **Counters always expire.** `hit_counter` sends `INCR` and `EXPIRE … NX` in one `MULTI`:
  the TTL is set on the first hit of a window and never extended, and a key that somehow
  lost its TTL gets one back on its next hit.
- **Invalidation.** Nothing deletes these keys by hand. A revoked session's marker outlives
  the longest access token that can carry its `sid`, then expires. A new trade link has a new
  key; the old verdict ages out.
- **Unavailable verdicts are not cached.** Only a real verdict (`ok`, `warn`, `bad`) is
  written to `users:tradelink:{…}`; an outage opens the breaker instead.
