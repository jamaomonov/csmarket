# P2P webhook relay

A Cloudflare Worker that lets one Telegram bot (the HUMO-notification reader shared with YuPay)
feed two projects. Spec `docs/superpowers/specs/2026-10-19-p2p-topup-design.md`, ADR-0021,
runbook `docs/runbooks/p2p.md`.

- Telegram → the Worker, with the relay's own secret.
- The Worker → YuPay and → csmarket, the body unchanged, each with that project's secret, in
  parallel.
- 200 to Telegram only when **both** answered 2xx; otherwise 502 and Telegram retries (both
  projects dedupe by message id).

## Deploy (the owner, once)

```sh
cd infra/p2p-relay
cp wrangler.toml.example wrangler.toml
npx wrangler login
npx wrangler secret put RELAY_SECRET     # a new random string
npx wrangler secret put YUPAY_URL
npx wrangler secret put YUPAY_SECRET
npx wrangler secret put CSMARKET_URL
npx wrangler secret put CSMARKET_SECRET
npx wrangler deploy                      # prints https://csmarket-p2p-relay.<account>.workers.dev
```

Then point the bot at it (the bot token is in YuPay's sops; do this in the YuPay session or by
hand, once YuPay's foreign-card filter is deployed):

```sh
curl -s "https://api.telegram.org/bot$TOKEN/setWebhook" \
  -d url=https://csmarket-p2p-relay.<account>.workers.dev \
  -d secret_token="$RELAY_SECRET" \
  -d 'allowed_updates=["business_message","business_connection"]'
curl -s "https://api.telegram.org/bot$TOKEN/getWebhookInfo"
```

## Test

```sh
apps/admin/node_modules/.bin/vitest run --root infra/p2p-relay
```
