# PII handling

The owner's rule, verbatim in substance: **never log PII — Steam ID, email, IP, trade-link
token.** Order numbers and amounts are fine. This file lists what personal data csmarket
holds, where it may appear, and where it never may. Update it with any change that adds a
field, a log line, a metric or a third party that sees one of these values (`AGENTS.md` § 5).

## Inventory

| Data                     | Stored in                                                  | Arrives in | Notes                                                                                                        |
| ------------------------ | ---------------------------------------------------------- | ---------- | ------------------------------------------------------------------------------------------------------------ |
| Steam ID (SteamID64)     | `users.steam_id`                                           | M1         | The identity. Public on Steam, still personal here: it links a person to purchases                           |
| Display name, avatar URL | `users.display_name`, `users.avatar_url`                   | M1         | Copied from Steam at sign-in                                                                                 |
| Email                    | `users.email` (optional)                                   | M1         | Only for receipts and order emails (M4)                                                                      |
| Trade link               | `users.trade_link`; a snapshot in `orders.trade_link` (M4) | M1         | Its `token` is a **credential**: anyone holding it can send that account offers. `partner` is the account id |
| Client IP                | **not stored** in Postgres                                 | M0         | Rate-limit counters only (below)                                                                             |

### Client IP

- The coarse limiter (slowapi, M0) keeps per-IP, per-route counters **in the API process's
  memory** for its window (one minute by default). Nothing is written to disk.
- `ip_guard` (M1) keeps per-IP counters in **Redis** under keys that expire with their window
  (60 s by default). Never in Postgres, never in a column.
- The trade-link verdict cache (M1) is keyed by a **hash** of the link, never the link.

## Where each may appear

| Channel                | Rule                                                                                                                                                                                                                                                  |
| ---------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Application logs       | **Never.** `core/logging.py` redacts by key (`steam_id`, `email`, `ip`, `trade_link`, `partner`, `token`, `user_id`, …) and by stem (`*email*`, `*steamid*`, `*_ip`, `*_token`). Use `hash_short()` when a log needs to correlate one person's events |
| Prometheus metrics     | **Never as a label.** Labels are bounded `Literal`s (`core/metrics.py`, rule 1)                                                                                                                                                                       |
| Sentry                 | `send_default_pii=False` (no bodies, headers, cookies, user) and `include_local_variables=False` (no stack-frame locals) — `core/observability.py`                                                                                                    |
| Traces, locals in logs | Off: structlog renders tracebacks with `show_locals=False`                                                                                                                                                                                            |
| URLs and query strings | Never carry a trade link or token — the edge logs full URLs. Advisory lookups that take one are `POST`                                                                                                                                                |
| Chat, docs, tests      | Never a real trade-link token or a real person's Steam ID; use redrawn / fake values                                                                                                                                                                  |
| Admin UI               | Shows what an operator needs to resolve an order (M1+); every admin action is audited in `admin_audit_log`                                                                                                                                            |
| Third parties          | Waxpeer receives the trade link to check it (M1) and its `partner` and `token` to deliver (M4); acquirers receive the order number and amount, not the Steam ID                                                                                       |

## Open gaps

- **Caddy access log.** `infra/caddy/Caddyfile.prod` logs every request as JSON to stdout,
  which Promtail ships to Loki — including the client address fields. That contradicts the
  rule above and must be filtered before the first production deploy. Remove this line when
  it is.

## Retention

Retention for `users` (deletion via `deleted_at`), orders, and backups is decided with the
modules that own them: M1 for accounts, M4 for orders and trades, M5 for backups.
