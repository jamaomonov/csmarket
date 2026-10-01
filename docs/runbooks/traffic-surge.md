# Runbook — a traffic surge

`ApiSaturated`, `ApiFileDescriptorsHigh`, `ApiHighLatency`, `ApiSupplierLatency`,
`PostgresConnectionsHigh`, `RedisMemoryHigh` and `RedisCeilingUnset`
(`infra/prometheus/alerts/api.yml`) link here. What limits throughput on this stack is
software, not hardware — read the ceilings first.

## The ceilings, by construction

| Ceiling                                | Where it is set                                                                       |
| -------------------------------------- | ------------------------------------------------------------------------------------- |
| **One core** for the whole API         | one uvicorn process, no `--workers` (`infra/docker/api.Dockerfile`)                   |
| **20 DB connections** per process      | `core/db.py`: `pool_size=10, max_overflow=10`; api, worker and scheduler each own one |
| **100** Postgres connections in total  | `max_connections=100` in `docker-compose.prod.yml`                                    |
| **256 MB** Redis, `noeviction`         | `--maxmemory 256mb` in `docker-compose.prod.yml`; container limit 384 MB              |
| **65 536** file descriptors (api, web) | `ulimits.nofile` in `docker-compose.prod.yml`                                         |
| **20 req/min** Waxpeer search          | Waxpeer's limit, shared by listings and mass-info (M2)                                |

One event loop on one core means CPU any endpoint burns is a ceiling for _every_ route.

## First checks when the site is slow

Prometheus is internal-only; query it from inside its container:

```bash
cd ~/opt/csmarket
q() { docker compose -f docker-compose.prod.yml exec -T prometheus \
  wget -qO- "http://localhost:9090/api/v1/query?query=$(python3 -c 'import sys,urllib.parse;print(urllib.parse.quote(sys.argv[1]))' "$1")"; }
q 'rate(process_cpu_seconds_total{job="api"}[5m])'
```

In order:

1. **API CPU** — `rate(process_cpu_seconds_total{job="api"}[5m])`. Above 0.85 the loop is
   full; this leads every other symptom by minutes.
2. **File descriptors** — `process_open_fds{job="api"} / process_max_fds{job="api"}`. Past
   ~0.7 you are near a hard wall: at the limit uvicorn stops accepting every connection,
   HTTP included, and does not recover on its own. From M4 each open WebSocket holds one.
3. **DB connections** — `sum(pg_stat_database_numbackends) / max(pg_settings_max_connections)`.
   Saturation shows up as 500s on every route at once, because the pool is shared.
4. **Status classes** — `sum by (status) (rate(http_requests_total{job="api"}[5m]))`. Codes
   are grouped by class (`4xx`, `5xx`); to see whether a `4xx` rise is our own limiter
   answering 429, read Caddy's access log in Loki: `{service="caddy"} |= "\"status\":429"`.
5. **Latency** — the histogram has explicit buckets up to 10 s
   (`bootstrap._LATENCY_BUCKETS`: 0.025 … 10), so p95 is measurable up to there.

**Two latency alerts, and which one you have.** `ApiHighLatency` (p95 > 1.5 s for 10 min)
excludes the Waxpeer-bound routes — `/skins/{slug}/listings` (M2) and the trade-link check
(M1). If it fires, something **we** own is slow. `ApiSupplierLatency` (p95 > 5 s for 15 min)
watches only those routes and means Waxpeer or Steam is degraded — check them before touching
anything here. A new upstream-bound route must be added to both `handler` regexes, or the
first alert starts crying wolf.

## `QueuePool limit … reached` — the pool, not the database

Sentry shows `TimeoutError: QueuePool limit of size 10 overflow 10 reached, connection timed
out`. A request waits the pool timeout before failing, so a short burst produces a cluster of
slow 500s.

**Check for amplification before raising the ceiling.** A handler holds its session for its
whole lifetime; anything it calls that opens a _second_ session from the same pool halves the
capacity exactly when load is high. A session held across an upstream HTTP call does the same.
Burst or trickle:

```bash
docker compose -f docker-compose.prod.yml logs api --since 24h -t \
  | grep -i "QueuePool limit" | awk '{print substr($1,1,16)}' | sort | uniq -c
```

One tight cluster is a burst — look for what fanned out. A steady trickle across hours is a
real capacity problem, and only then is a bigger pool the answer — remembering that api,
worker and scheduler share Postgres's 100 connections.

## Rate limits, and which one is biting

**The global limiter** (`bootstrap._build_limiter`) is slowapi in process memory, keyed by
client IP and bucketed **per route**, `CSMARKET_RATE_LIMIT_DEFAULT` (default `600/minute`).
Exempt: `/healthz`, `/readyz` and — from M3 — the acquirer webhooks
(`bootstrap._exempt_self_authenticating_routes`; never remove one without reading why it is
there: a 429 to an acquirer costs money and buys nothing).

Two things share a bucket by design and are worth checking first in a 429 spike:

- visitors behind one carrier NAT (one address for many people);
- the storefront's server rendering: `web` calls `http://api:8000` directly
  (`API_INTERNAL_URL`), without Caddy, so all server-side requests carry the `web`
  container's address.

To loosen it, set `CSMARKET_RATE_LIMIT_DEFAULT` in `secrets/api.env` and recreate the api
([`deploy.md`](deploy.md#changing-a-secret); the tag comes from `.env`) — `up -d`, not `restart`.

**`ip_guard`** (M1) is the Redis-backed limiter on sign-in, trade-link check, order and
top-up creation, with its own buckets per route. It answers problem+json with `Retry-After`.

## Redis is full

`maxmemory` is 256 MB and the policy is **`noeviction` on purpose**. Redis holds no work queue
(the queue is the `orders` table); it holds rate-limit and `ip_guard` counters (M1), caches
(M1+, catalogued in `docs/architecture/cache-keys.md`) and, from M4, the realtime pub/sub.
Evicting any of that would silently weaken a limit or drop a cached value; refusing writes is
the correct failure.

Before raising the ceiling, find what grew:

```bash
docker compose -f docker-compose.prod.yml exec -T redis \
  sh -c 'redis-cli -a "$REDIS_PASSWORD" --no-auth-warning --bigkeys'
```

A key with no TTL, or a TTL longer than its catalogue entry says, is the usual cause.

## Memory pressure on the host

Every container in `docker-compose.prod.yml` has a `mem_limit` sized as a ceiling for a box
without swap, where pressure goes straight to the OOM killer. If a container exits 137, find
what actually grew before tightening its neighbours: a limit set too tight turns into a
restart loop, and for Postgres that means repeated crash recovery.

## What degrades on its own

- **Item listings** (M2) — on an exhausted Waxpeer budget, an open breaker or a 429 they
  answer from the 5-minute snapshot with `degraded: true`. Nothing to do.
- **Trade-link check** (M1) — advisory; an outage answers "could not check" and never blocks
  checkout.
- **Buying at Waxpeer** (M4) — runs in the worker off the request path. A slow Waxpeer delays
  deliveries, not checkouts; `paid` orders wait in the table and are claimed when it recovers.

## Deploys during a surge

Deploys are stop-then-start, not rolling: Caddy holds requests for up to 15 s, and migrations
run before the new code starts. Do not deploy into a surge unless the deploy is the fix.

## Alerting

Alerts go to the ops Telegram chat through Alertmanager, prefixed `[csmarket]`.
`infra/alertmanager/alertmanager.tmpl.yml` is a template; the compose entrypoint substitutes
`ALERT_BOT_TOKEN` and `ALERT_CHAT_ID` from `secrets/alertmanager.env` at start-up.
Alertmanager is in the `ops` compose profile and runs only once M5 sets
`COMPOSE_PROFILES=ops` in `~/opt/csmarket/.env` ([first deploy, step 9](first-deploy.md#9-backups-and-alerts-m5));
before that no alert leaves the box.

**If alerts stop arriving**, check in this order (step 0: `grep COMPOSE_PROFILES .env` says `ops`):

1. `docker compose -f docker-compose.prod.yml exec -T prometheus wget -qO- http://localhost:9090/api/v1/alertmanagers`
   — an empty `activeAlertmanagers` means Prometheus is not wired to it.
2. `docker compose -f docker-compose.prod.yml logs alertmanager` — a bad token shows up as a
   Telegram API rejection here and nowhere else.
3. `docker compose -f docker-compose.prod.yml exec -T alertmanager grep -c __ALERT_ /alertmanager/alertmanager.yml`
   — anything but `0` means the substitution did not run.

**Repeat intervals are long on purpose** — 4 h, and 1 h for `page`: an alert that repeats
every few minutes trains people to mute the chat. **Two inhibitions**: `ApiDown` silences the
API's saturation, latency, error-rate and descriptor alerts; `PostgresDown` silences
`PostgresConnectionsHigh`.

The order-pipeline alerts in spec §12 (`paid` orders older than 5 min, `trade_sent` without a
poll result for 30 min, Waxpeer balance, audit divergences, webhook signature failures) arrive
with the modules that emit them (M3–M5).
