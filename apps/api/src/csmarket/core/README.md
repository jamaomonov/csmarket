# core — shared kernel

Ported by allow-list (spec §3.2). What it owns here:

| Module          | Owns                                                                                   |
| --------------- | -------------------------------------------------------------------------------------- |
| `config`        | `Settings` — every var is `CSMARKET_*`; `get_settings()` cached                        |
| `logging`       | structlog setup, PII redaction (Steam ID, email, IP, trade link, tokens), `hash_short` |
| `clock`, `ids`  | `now()` (pinnable), UUIDv7 `new_id()`                                                  |
| `db`, `redis`   | async engine/session factory with the naming convention; short-timeout Redis client    |
| `errors`        | `AppError` → RFC 7807 problem+json, `Retry-After` promotion                            |
| `cache_headers` | `Cache-Control: no-store` unless a route says otherwise                                |
| `client_ip`     | first `X-Forwarded-For` entry — relies on Caddy overwriting the header                 |
| `metrics`       | domain Prometheus counters (`csmarket_*`), two rules in the docstring                  |
| `money`         | `format_amount` for alerts: UZS whole, USD two decimals                                |
| `idempotency`   | `Idempotency-Key` validation + generic replay store (`idempotent_responses`)           |
| `events`        | `DomainEvent` envelope                                                                 |
| `crypto`        | HKDF purpose keys off `CSMARKET_APP_ENC_KEY`, SecretBox encrypt/decrypt                |
| `health`        | bounded Postgres/Redis checks behind `/readyz`                                         |
| `observability` | `init_sentry` with both PII switches off                                               |

Not ported: `outbound*` (merchant-webhook delivery) and `outbox` (a Protocol nothing
implemented; the `orders` table is our queue — ADR-0002).
