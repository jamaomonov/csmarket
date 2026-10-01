# Redis cache keys

Every Redis key the app writes is listed here, one row per key (`AGENTS.md` § 5). A new key
lands in the same change as its code.

**No key holds a raw IP, Steam ID, email, trade link or token.** Identifiers are hashed
before they go into a key: `hash_short()` (12 hex characters) for an IP, a SHA-256 prefix
(32 hex characters) for a subject or a link. A key is not a log, but `MONITOR` and `SCAN`
read it, so the rule is the same as for logs (`docs/security/pii-handling.md`).

| Key                                                               | TTL                                           | Written by                                                                                                | Read by                                                                               | PII?                                                                    |
| ----------------------------------------------------------------- | --------------------------------------------- | --------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------- | ----------------------------------------------------------------------- |
| `auth:revoked:{jti}`                                              | the access token's remaining life (≤ 900 s)   | `auth.service.logout` (a Bearer on sign-out)                                                              | `auth.service` on every authenticated request                                         | No: `jti` is a random token id                                          |
| `auth:revoked_sid:{sid}`                                          | 900 s (`jwt_access_ttl_seconds`)              | `auth.service` when a session is revoked                                                                  | `auth.service` on every authenticated request                                         | No: `sid` is a random session id                                        |
| `auth:ipguard:{bucket}:{hash_short(ip)}`                          | window, 60 s (`auth_ip_guard_window_seconds`) | `auth.ip_guard.guard_ip`                                                                                  | `auth.ip_guard.guard_ip` (INCR + EXPIRE NX, then compare)                             | Digest of the IP only; the raw IP is never stored                       |
| `auth:ipguard:{bucket}:{hash_short(ip)}:s:{sha256(subject)[:32]}` | window, 60 s                                  | `auth.ip_guard.guard_ip` when a `subject` is given                                                        | `auth.ip_guard.guard_ip`                                                              | Digests only (IP, and the subject: the user id for `trade-link-check`)  |
| `users:tradelink:{sha256(link)[:32]}`                             | 600 s                                         | `users.tradelink.check_trade_link`                                                                        | `users.tradelink.check_trade_link`                                                    | Value is `{verdict, reason}` only; the key is a digest of the link      |
| `users:tradelink:breaker`                                         | 60 s                                          | `users.tradelink.check_trade_link` on any upstream failure                                                | `users.tradelink.check_trade_link`                                                    | No                                                                      |
| `skins:pricing`                                                   | 3600 s                                        | `skins.settings.load_rules` (on a miss), `publish_rules`                                                  | `skins.settings.load_rules`                                                           | No: the pricing rules document                                          |
| `fx:usd_uzs`                                                      | 86 400 s                                      | `fx.service.refresh_usd_uzs` (scheduler `fx.refresh`), `current_usd_uzs` (on a miss)                      | `fx.service.current_usd_uzs`                                                          | No: the rate, snapshot id, fetch time and source                        |
| `skins:job:{import\|price_sync}`                                  | none (overwritten each run)                   | `skins.job_status.record_job` (scheduler `skins.catalog_import`, price sync)                              | `skins.job_status.read_job` (admin status card)                                       | No: finished_at, ok, counters, our own error label                      |
| `skins:catalog:ver`                                               | none (an integer, `INCR`)                     | `skins.cachekeys.bump_catalog_version` (after every price tick commit and every admin hide / alias write) | `skins.cachekeys.catalog_version` (every cached catalogue page carries it in its key) | No: a counter                                                           |
| `skins:{catalog\|facets\|suggest}:{ver}:{sha1}`                   | 60 s                                          | `skins.routes._cached` (on a miss)                                                                        | `skins.routes._cached` (`GET /skins/catalog`, `/facets`, `/suggest`)                  | No: a public page body; the key is a digest of the query (and the rate) |
| `skins:listings:{slug}`                                           | 90 s (fresh)                                  | `skins.listings.listings_for` (after a live Waxpeer read)                                                 | `skins.listings.listings_for` (`GET /skins/{slug}/listings`)                          | No: public listing data (ids, prices, floats, stickers)                 |
| `skins:listings:{slug}:stale`                                     | 3600 s                                        | `skins.listings.listings_for` (twin of the fresh key)                                                     | `skins.listings.listings_for` when the live read is not possible                      | No: as above                                                            |
| `skins:wax:breaker`                                               | 120 s                                         | `skins.listings.listings_for` on a Waxpeer 429 or outage                                                  | `skins.listings.listings_for` (open: no live call)                                    | No                                                                      |
| `skins:wax:budget:{YYYYMMDDHHMM}`                                 | 120 s                                         | `skins.listings.listings_for` (`INCR` per live attempt)                                                   | `skins.listings.listings_for` (over `skins_listings_budget_per_minute`: no live call) | No: a counter per UTC minute                                            |

## Notes

- **Catalogue version.** `skins:catalog:ver` is not a cache entry but the number inside every
  cached catalogue page key; a bump expires all of them at once. It has no TTL (losing it to a
  flush just restarts the count at 0, and old keys age out by their own 60 s TTL). Unreadable
  Redis reads as version 0, so pages miss the cache; a failed bump is swallowed.

- **Catalogue pages.** `skins:{catalog|facets|suggest}:{ver}:{sha1}` holds the JSON body of
  one public page for 60 s. `ver` is `skins:catalog:ver`, so a bump orphans every page at once;
  the SHA-1 digest of the query (plus the soʻm rate for catalogue and suggest) keeps arbitrary
  search text out of key names. A Redis error on read or write is swallowed and the page is
  built from Postgres.

- **Live listings.** `GET /skins/{slug}/listings` reads `skins:listings:{slug}` first (90 s). On a
  miss it makes one Waxpeer search if the breaker is closed and the process-wide budget
  (`skins:wax:budget:{minute}`, 18 per minute, under Waxpeer's 20) has room; a 429 or outage
  opens the breaker for 120 s. Without a live answer it serves the 1 h stale twin, then the
  last price snapshot's `cheapest_auto`, both with `degraded: true`. A Redis error on any of
  these is swallowed (a failed budget `INCR` counts as "room left").

- **Pricing rules.** `skins:pricing` (3600 s) is the rules document; the price sync reads the
  rules fresh from Postgres, so a stale copy never prices a tick.

- **Job status.** `skins:job:{import|price_sync}` is overwritten on every run and has no TTL; a
  flush only empties the admin status card until the next run.

- **Rate.** `fx:usd_uzs` (86 400 s) is a copy of the newest `fx_snapshots` row; Redis down or a
  corrupt copy falls through to Postgres. The soʻm rate is part of the catalogue and suggest
  page keys' digest.

- **Buckets** in use: `steam-login`, `dev-login` (sign-in routes, no subject),
  `trade-link-check` (IP plus user id) and `skins-listings` (IP only; a cache miss spends Waxpeer
  quota, so the bucket bounds distinct items per address). Per-bucket ceilings: `auth_ip_guard_bucket_max`
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
