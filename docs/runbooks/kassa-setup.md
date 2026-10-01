# Runbook — kassa setup (Click, Payme, Uzum)

What to enter in each kassa's cabinet, where each secret goes, how to switch from sandbox to
production, and the first real top-up after a deploy. Design: ADR-0006. Troubleshooting:
[`click.md`](./click.md), [`payme.md`](./payme.md), [`uzum.md`](./uzum.md); the ledger:
[`wallet.md`](./wallet.md).

All three kassas call **us**: we are their callback server. None of them sends a webhook we
subscribe to. Each top-up has a number `T` + 7 characters (e.g. `T7K3M9QX`); that number is
the account value every kassa sends back.

Commands run on the VPS in `~/opt/csmarket` (`IMAGE_TAG` is pinned in `.env`; never export
one by hand — [`deploy.md`](./deploy.md)). Secrets go in `secrets/api.env`; after editing it,
recreate what reads it: `docker compose -f docker-compose.prod.yml up -d api worker scheduler`.
Never paste a key or password into chat, tickets or this repo; the logger redacts them.

## Which kassas are on

A kassa is offered (its tile shows on the balance page) only when its credentials are set;
otherwise its callbacks refuse every call. Check:

```bash
curl -s https://api.csmarket.uz/api/v1/payments/providers
# {"providers":[{"slug":"click"},{"slug":"payme"},{"slug":"uzum"}]}   — never "mock" in prod
```

## Common to all three

- **Currency:** soʻm, whole. Click sends soʻm; Payme and Uzum send **tiyin** (soʻm × 100);
  Uzum's `/check` answer gives the amount back in whole soʻm.
- **Limits:** one top-up is 1 000 – 10 000 000 soʻm (owner decision D1). If the cabinet has
  min/max fields, enter the same.
- **Return URL:** nothing to enter. Every checkout link carries our own page,
  `https://csmarket.uz[/uz|/en]/account/balance/topups/{number}`.
- **Refunds:** only from the kassa's own cabinet. The kassa calls our cancel / reverse; we
  take the money back off the balance if it is still there, else we refuse (Payme −31007,
  Uzum 10017; Click has no merchant reversal). Never "refund" by editing the database.
- **Timeouts:** an unfinished kassa transaction is closed by our sweep — Click 30 min,
  Payme 12 h, Uzum 30 min. A top-up no kassa touched expires after 30 min.

## Click

Cabinet: `merchant.click.uz`, the csmarket web service.

| Field          | Value                                                                                        |
| -------------- | -------------------------------------------------------------------------------------------- |
| Prepare URL    | `https://api.csmarket.uz/api/v1/payments/click/prepare`                                      |
| Complete URL   | `https://api.csmarket.uz/api/v1/payments/click/complete`                                     |
| Request format | POST, `application/x-www-form-urlencoded` (Click's default). JSON or multipart is refused −8 |
| Account field  | `merchant_trans_id` = the top-up number (the pay link sends it as `transaction_param`)       |
| Currency       | soʻm (Click sends e.g. `50000.00`)                                                           |
| IP allowlist   | none (Click publishes none); the MD5 signature is the gate                                   |

`secrets/api.env`:

```bash
CSMARKET_CLICK_MERCHANT_ID=…    # merchant id
CSMARKET_CLICK_SERVICE_ID=…     # the web service id (one service only)
CSMARKET_CLICK_SECRET_KEY=…     # the service's SECRET_KEY
# CSMARKET_CLICK_PAY_URL=https://my.click.uz/services/pay   (default)
```

All three must be set. Another `service_id`, or a blank secret, answers −1 to every call.

**Sandbox → prod:** ask Click whether the SECRET_KEY changes for production (the ids usually
do not). Swap the key, recreate `api`, run the first real top-up below and check that
`/prepare` then `/complete` arrive in that order.

## Payme

Cabinet: `merchant.paycom.uz` → the cash register («касса»).

| Field                                 | Value                                                                                     |
| ------------------------------------- | ----------------------------------------------------------------------------------------- |
| Endpoint URL («Адрес конечной точки») | `https://api.csmarket.uz/api/v1/payments/payme/merchant`                                  |
| Protocol                              | POST, JSON-RPC 2.0 (Payme's default)                                                      |
| Account field («Поле аккаунта»)       | **one** field named **`order`**, string = the top-up number; one payment per account      |
| Login                                 | `Paycom` (Payme sends it; we compare)                                                     |
| Keys                                  | «Ключ» (production) and «Тестовый ключ» (sandbox) — both are accepted at once             |
| Currency                              | soʻm; Payme sends tiyin (100 000 – 1 000 000 000 for D1's limits)                         |
| IP allowlist                          | `185.234.113.0/28`, enforced in Caddy (`infra/caddy/Caddyfile.prod`) on top of Basic auth |

`secrets/api.env`:

```bash
CSMARKET_PAYME_MERCHANT_ID=…    # cash register id
CSMARKET_PAYME_KEY=…            # «Ключ»
CSMARKET_PAYME_TEST_KEY=…       # «Тестовый ключ»
# CSMARKET_PAYME_LOGIN=Paycom                               (default)
# CSMARKET_PAYME_CHECKOUT_URL=https://checkout.paycom.uz    (default; https://test.paycom.uz for the sandbox)
```

Payme is offered with the merchant id and either key.

**Sandbox (`test.paycom.uz`):** register the endpoint with the test key, set
`CSMARKET_PAYME_CHECKOUT_URL=https://test.paycom.uz`, open a fresh top-up through Payme on the
site and use its number (an already paid one answers −31051). Run Payme's automated suite;
both sequences must be green:

- unconfirmed: wrong auth −32504 → wrong amount −31001 → unknown account −31050 → Check →
  Create → Cancel (state −1);
- confirmed: Check → Create → Perform → Cancel (state −2, the balance goes back).

**Go-live:** the production key in `CSMARKET_PAYME_KEY`, remove the
`CSMARKET_PAYME_CHECKOUT_URL` override (back to `checkout.paycom.uz`), recreate `api`. The test
key may stay: the sandbox keeps working on the same endpoint.

## Uzum

Uzum Bank sets the service up on its side; hand its integration engineer the values below.

| Field                                    | Value                                                                                |
| ---------------------------------------- | ------------------------------------------------------------------------------------ |
| Callback base URL                        | `https://api.csmarket.uz/api/v1/payments/uzum`                                       |
| Endpoints                                | `/check`, `/create`, `/confirm`, `/reverse`, `/status`; all POST, `application/json` |
| Payment attribute (additional parameter) | **`order`** (string) = the top-up number — see the note below                        |
| Auth                                     | HTTP Basic, a login/password pair per environment (production and sandbox)           |
| `serviceId`                              | the service id Uzum issues; must equal `CSMARKET_UZUM_SERVICE_ID`                    |
| Units                                    | tiyin on create/confirm/reverse/status; whole soʻm in `/check`'s `data.amount.value` |
| IP allowlist                             | none yet (Uzum publishes no range); Basic auth is the gate                           |

**The attribute name and the checkout link must match.** Our checkout link is
`https://uzumbank.uz/open-service?serviceId=<id>&order=<number>&redirectUrl=<our page>` (no
amount: Uzum's app prefills it from our `/check`). Ask Uzum to name the cabinet attribute
**`order`**, the same string as the link parameter. If they cannot (YuPay's service used
`orderId`), change the link parameter in `apps/api/src/csmarket/modules/payments/gateways/uzum.py`
to their name — the callbacks already accept `order`, `orderId` and `order_id`. A mismatch
does not break the callbacks, it breaks the prefilled amount in Uzum's app.

`secrets/api.env`:

```bash
CSMARKET_UZUM_SERVICE_ID=…
CSMARKET_UZUM_LOGIN=…           # production pair
CSMARKET_UZUM_PASSWORD=…
CSMARKET_UZUM_TEST_LOGIN=…      # sandbox pair
CSMARKET_UZUM_TEST_PASSWORD=…
# CSMARKET_UZUM_OPEN_SERVICE_URL=https://uzumbank.uz/open-service   (default)
```

Uzum is offered with the service id and one whole pair. Confirm with Uzum who issues the
production pair (YuPay's sandbox pair was generated by us).

**Sandbox:** set the service id and the sandbox pair, recreate `api`, and hand over the base
URL, the pair, the service id and `docs/api/uzum.postman_collection.json` (fill in its
variables; use a fresh unpaid top-up number and its amount × 100). Sequences: check → create →
confirm → status; create → reverse; confirm → reverse (the balance goes back). Replays answer
10010 / 10016 / 10018. Every error is HTTP 400 with an `errorCode` — that is Uzum's contract,
not a failure. **Tell the tester:** a 10001 (bad login/password) answer carries no
`serviceId` / `transId` echo, because auth is checked before the body is read.

**Go-live:** the production pair in env, recreate `api`, run the first real top-up. Once it
passes, **delete the sandbox pair** and recreate `api` again: both pairs are accepted at once,
and a live sandbox pair is a second key to `/confirm`.

## First real top-up after a deploy (R14)

This is M3's "done when". Run it once per kassa, from a real card, after the cabinet points
at production.

1. `curl -s https://api.csmarket.uz/api/v1/payments/providers` lists the kassa.
2. Sign in on `https://csmarket.uz/account/balance` with a test account. Choose the kassa,
   enter **1 000**, press «Пополнить на 1 000 сум». The kassa page opens.
3. Pay. You are returned to `/account/balance/topups/T…`; within seconds it says «Баланс
   пополнен на 1 000 сум».
4. «К балансу»: the balance grew by 1 000 and the history shows «Пополнение» with this
   number.
5. Admin → «Платежи» → search the number: the attempt is «оплачен», the top-up «зачислено»,
   and «Транзакции кассы» shows the kassa's row «подтверждён» (Click) / «проведена» (Payme) /
   «подтверждён» (Uzum; the raw code is in the tooltip).
6. Reverse it from the kassa's side where possible: Payme — cancel the transaction in the
   cabinet; Uzum — ask the engineer to reverse it. (Click has no merchant reversal: skip.)
   The admin payment becomes «возвращён», the top-up «отменено кассой», the history shows
   «Пополнение отменено», and the balance is 1 000 lower again.
7. If the balance was spent in between, the kassa reports a refusal (−31007 / 10017): that
   is the designed behaviour, not a bug.

Any step failing: the kassa's runbook, section "Customer paid, balance not credited".

## Rejections

Alert `KassaRejectionsSpike` (`infra/prometheus/alerts/payments.yml`): more than 20 callbacks
from one kassa refused **before any business logic** in 15 minutes, by
`csmarket_kassa_rejections_total{provider, reason}`:

| `reason`    | Means                                                                    |
| ----------- | ------------------------------------------------------------------------ |
| `signature` | Click: the MD5 `sign_string` did not match, or another `service_id` (−1) |
| `auth`      | Payme −32504, Uzum 10001: the Basic login/key did not match              |
| `malformed` | A body the protocol does not allow (bad JSON, missing field, not POST)   |

What to do:

1. **Did a secret or cabinet setting change?** A rotated key in the cabinet that is not yet in
   `secrets/api.env` (or the other way round) makes **every** genuine callback fail, and
   top-ups through that kassa stop. Compare the cabinet with `secrets/api.env`; fix, then
   recreate `api`.
2. **Is it the right environment?** Sandbox traffic needs the test key / test pair to be set
   too.
3. **Otherwise it is probing.** Callbacks are anonymous by design; a refused call changes
   nothing. Watch that real top-ups keep succeeding (admin «Платежи», status «оплачен»).

**Payme's IP allowlist is invisible to this metric.** Caddy answers 403 to a Payme-path call
from outside `185.234.113.0/28` before it reaches the app, so nothing is counted. The symptom
is Payme top-ups stopping with no alert. Check the Caddy access log:

```bash
docker compose -f docker-compose.prod.yml logs --since 1h caddy | grep 'payme/merchant' | grep '"status":403'
```

(The log keeps method, path and status, never the client address — `pii_filter`.) A run of
403s while Payme says it is calling means the edge no longer resolves Payme's real address
(Cloudflare or `client_ip` wiring — ADR-0003), or Payme changed its range.
