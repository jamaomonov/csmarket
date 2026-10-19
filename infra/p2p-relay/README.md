# P2P webhook relay

A Cloudflare Worker that lets one Telegram bot (the HUMO-notification reader shared with YuPay)
feed two projects. Spec `docs/superpowers/specs/2026-10-19-p2p-topup-design.md`, ADR-0021,
runbook `docs/runbooks/p2p.md`.

- Telegram → the Worker, with the relay's own secret.
- The Worker → YuPay synchronously, the body unchanged, with YuPay's secret: Telegram gets 200
  exactly when YuPay answered 2xx (502 otherwise, and Telegram retries).
- The Worker → csmarket on its own (agreed with the YuPay session): through the Cloudflare Queue
  `csmarket-p2p` (retries every 30 s for ~50 min, then `csmarket-p2p-dlq`), so csmarket being
  down never stops YuPay's payments. Both projects dedupe by message id.

## Deploy (the owner, once)

```sh
cd infra/p2p-relay
cp wrangler.toml.example wrangler.toml
npx wrangler login
npx wrangler queues create csmarket-p2p
npx wrangler queues create csmarket-p2p-dlq
npx wrangler secret put RELAY_SECRET     # a new random string
npx wrangler secret put YUPAY_URL
npx wrangler secret put YUPAY_SECRET
npx wrangler secret put CSMARKET_URL
npx wrangler secret put CSMARKET_SECRET
npx wrangler deploy                      # prints https://p2p-relay.csmarket.uz
```

Then point the bot at it (the bot token is in YuPay's sops; do this in the YuPay session or by
hand, once YuPay's foreign-card filter is deployed):

```sh
curl -s "https://api.telegram.org/bot$TOKEN/setWebhook" \
  -d url=https://p2p-relay.csmarket.uz \
  -d secret_token="$RELAY_SECRET" \
  -d 'allowed_updates=["business_message","business_connection"]'
curl -s "https://api.telegram.org/bot$TOKEN/getWebhookInfo"
```

## Test

```sh
apps/admin/node_modules/.bin/vitest run --root infra/p2p-relay
```
