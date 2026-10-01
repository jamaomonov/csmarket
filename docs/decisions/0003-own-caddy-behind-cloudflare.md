# 0003. Own Caddy behind Cloudflare

- **Status**: Accepted
- **Date**: 2026-10-01
- **Deciders**: @jamaomonov
- **Tags**: infra | security

## Context and problem statement

YuPay runs a separate, shared edge proxy (YuPay ADR-0030): a third compose project owns
`:80`/`:443` and forwards each hostname to the owning stack's internal Caddy over a shared
docker network. That shape exists only because YuPay's VPS is co-hosted with an unrelated
stack that also needs those ports.

csmarket has its own VPS (spec §2 item 7, §12) and is alone on it. Cloudflare proxies every
csmarket hostname (`csmarket.uz`, `www`, `api`, `admin`, `grafana`) for its WAF and to keep
the site reachable when the transit path to the VPS is not. Who terminates TLS on the box,
and how does the API learn the visitor's real address through two proxies?

## Decision drivers

- Fewer moving parts on a single box.
- Real certificates at the origin, so Cloudflare can run in **Full (strict)**.
- One trustworthy client IP for the rate limiter and (from M1) `ip_guard` — a spoofable value
  makes both worthless, a constant one (Cloudflare's address) makes every visitor share a bucket.

## Considered options

1. **Copy YuPay's shared edge** — a separate edge compose project plus an internal Caddy.
2. **The stack's own Caddy owns `:80`/`:443`** directly.
3. **Cloudflare origin certificates** instead of Let's Encrypt.

## Decision outcome

**Chosen option: 2.** `caddy` in `docker-compose.prod.yml` publishes `80` and `443`,
terminates TLS with Let's Encrypt certificates obtained over ACME HTTP-01 (the challenge
reaches the origin through the Cloudflare proxy), and routes by host
(`infra/caddy/Caddyfile.prod`).

Client IP, end to end:

- The global block sets `trusted_proxies static <Cloudflare ranges>` and
  `client_ip_headers Cf-Connecting-Ip`: Caddy reads `Cf-Connecting-Ip` only when the TCP peer
  is a Cloudflare address, and uses the socket peer otherwise.
- Every upstream block **overwrites** `X-Forwarded-For` with `{client_ip}`
  (`header_up X-Forwarded-For {client_ip}`), so the API receives exactly one value.
- `apps/api/src/csmarket/core/client_ip.py` trusts the first `X-Forwarded-For` entry. The api
  port is not published, so nothing reaches FastAPI around Caddy.

No Caddy `rate_limit` (it needs a custom build); per-route limits live in FastAPI (slowapi)
and the volumetric tier is Cloudflare's WAF.

### Positive consequences

- One compose file and one network fewer than YuPay; one place to read routing, CSP and
  basic-auth.
- A request that bypasses Cloudflare cannot choose its rate-limit bucket: it gets its socket
  address.
- Ordinary Let's Encrypt certificates — the origin also works with the proxy switched off.

### Negative consequences

- Cloudflare's SSL mode must be **Full (strict)**; "Flexible" talks cleartext to an HTTPS
  origin and loops the redirect.
- The Cloudflare ranges are pinned in the Caddyfile. When Cloudflare publishes new ones they
  must be refreshed; until then a visitor arriving over a new range is seen as that range's
  edge address (fails safe — shared bucket, never a spoofable one).
- A first certificate may need the record set to DNS only for a moment if the Cloudflare zone
  redirects HTTP to HTTPS before the origin has a certificate (`docs/runbooks/first-deploy.md`).
- Editing the single-file Caddyfile bind mount needs `up -d --force-recreate caddy`; the
  deploy workflow does it when the file's hash changes.

## Validation

- `caddy validate` on `Caddyfile.prod` (M0 infra task).
- `apps/api/tests/unit/test_client_ip.py` pins the "first entry only" contract.
- The first-deploy runbook's client-IP check: a spoofed `X-Forwarded-For` never reaches the
  API.

## Alternatives considered (detail)

### Option 1 — shared edge

Solves a problem csmarket does not have, at the cost of a second compose project, an external
network and two Caddyfiles to keep in step.

### Option 3 — Cloudflare origin certificates

Removes ACME from the box, but the origin then only works behind Cloudflare (the certificate
is trusted by nobody else), and the certificate becomes one more secret to place and rotate.

## References

- YuPay ADR-0030 (shared edge proxy on a co-hosted VPS), in `~/Projects/yupay/docs/decisions/`
- `infra/caddy/Caddyfile.prod`, `docker-compose.prod.yml`, `apps/api/src/csmarket/core/client_ip.py`
- Cloudflare IP ranges: <https://www.cloudflare.com/ips-v4>, <https://www.cloudflare.com/ips-v6>
