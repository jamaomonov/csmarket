# Runbook — Click (Shop API)

Click calls two endpoints of ours while the customer pays in Click Up or on `my.click.uz`:
`POST /api/v1/payments/click/prepare`, then `/complete`. We own the transaction state
(`click_transactions.status`). Top-ups only in M3. Setup: [`kassa-setup.md`](./kassa-setup.md);
reference: `apps/api/src/csmarket/modules/click/README.md`; design: ADR-0006.

## Quick checks

- **Click tile missing.** All three of `CSMARKET_CLICK_MERCHANT_ID`, `CSMARKET_CLICK_SERVICE_ID`,
  `CSMARKET_CLICK_SECRET_KEY` must be set. `curl -s https://api.csmarket.uz/api/v1/payments/providers`.
- **Always HTTP 200.** Every outcome is `{"error", "error_note"}` at 200, even a stray GET
  (−8). If Click reports a "connection error", the request most likely never reached the API:
  look for it in the Caddy log (`docker compose -f docker-compose.prod.yml logs --since 1h caddy | grep payments/click`)
  before reading application logs.
- **Form, not JSON.** We accept only `application/x-www-form-urlencoded` (≤ 8 KiB, ≤ 32
  fields). If every call fails at once with −8, check the `Content-Type` Click sends.

## Customer paid, balance not credited

1. Get the top-up number (`T…`) from the customer (it is in the address of their status page)
   or from their admin card («Пополнения»).
2. Admin → «Платежи» → search the number → open the Click attempt → «Транзакции кассы».
3. Read the Click row:
   - **none** — `/prepare` never reached us: reachability (Caddy log above, DNS, the URL in
     the cabinet), or it was refused before a row was written (−1 signature, −5 / −9 not
     payable — see `api` logs `click.callback method=prepare error=…` with the number).
   - **`PREPARED` (подготовлен)** — Click has not called `/complete` yet. Wait; after 30 min
     the sweep cancels it. Ask Click about the `click_trans_id` if the customer has a debit.
   - **`CONFIRMED` (подтверждён)** — paid and credited. The attempt is «оплачен», the top-up
     «зачислено», the history shows «Пополнение». Ask the customer to reload.
   - **`CANCELLED` (отменён)** — no money was taken by us: Click aborted, the sweep closed it,
     or it was a second charge we refused (below). If the customer still sees a debit, it is
     Click's to return.
4. Never credit by hand in the database. If money truly reached us without a credit, use the
   admin balance adjustment with a reason that names the number (`wallet.md`), and tell the
   owner.

## Error codes

| Code | Meaning                                                                  | Action                                                              |
| ---- | ------------------------------------------------------------------------ | ------------------------------------------------------------------- |
| 0    | Success                                                                  | —                                                                   |
| −1   | Bad signature, another `service_id`, or no secret set                    | Sign-check below                                                    |
| −2   | Amount is not the top-up's in soʻm                                       | A tiyin amount or a tampered link; the customer starts a new top-up |
| −3   | `action` not 0 / 1                                                       | Not Click; a stray caller                                           |
| −4   | Already paid; complete replayed; a second charge refused                 | Harmless for a replay; for a second charge see below                |
| −5   | No such top-up number                                                    | A broken link                                                       |
| −6   | Unknown `merchant_prepare_id`, or it does not match the other fields     | Did `/prepare` land and commit? Check the Click row                 |
| −7   | Internal error or a failed commit                                        | `api` logs `click.webhook.internal_error`; Click retries            |
| −8   | Malformed: missing / non-numeric field, not urlencoded, not POST         | Check the raw method and `Content-Type`                             |
| −9   | Top-up expired or reversed; row cancelled; Click sent a negative `error` | The customer starts a new top-up                                    |

## Sign-check (−1)

- The MD5 is over the **raw** strings Click sent (`"1000.00"` ≠ `"1000"`):
  prepare `md5(click_trans_id + service_id + SECRET_KEY + merchant_trans_id + amount + action + sign_time)`;
  complete adds `merchant_prepare_id` right after `merchant_trans_id`.
- A −1 on **every** call means the secret or the service id in `secrets/api.env` does not
  match the cabinet (or is blank after a deploy). The alert `KassaRejectionsSpike`
  (`reason="signature"`) fires on it — [`kassa-setup.md#rejections`](./kassa-setup.md#rejections).
- Never log or print the secret to debug; compare the env file with the cabinet.

## Second charge refused

A retried checkout can create two Click transactions on one top-up. The first `/complete`
credits; a later `/complete` on the same top-up (or one already paid through Payme / Uzum)
answers −4 and its row is committed as `CANCELLED`, so Click does not take the money twice.
Log: `click.complete.second_charge_refused number= amount=`. Nothing to do unless the customer
reports a double debit — then it is Click's to return.

## Timeout sweep

Scheduler job `click.timeout`, every 5 min (first run 160 s after start): `PREPARED` rows older
than 30 min become `CANCELLED` and their attempt is released (only if no other `PREPARED` row
holds it). Logs: `click.timeout.done count=`, `click.timeout.row_failed`,
`click.timeout.crashed`. A `PREPARED` row hours old with no `done` lines means the scheduler is
not running: `docker compose -f docker-compose.prod.yml ps scheduler`.

A `CONFIRMED` row never changes, and a settled attempt is never cancelled. Seeing either
happen is a bug: stop and escalate.

## Never

- Never credit a balance in SQL or insert ledger rows by hand; use the admin adjustment with a
  reason (`wallet.md`).
- Never change a `click_transactions` row by hand.
- Never paste the SECRET_KEY into chat or a ticket.
