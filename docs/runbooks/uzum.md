# Runbook — Uzum Bank (Merchant API)

Uzum calls five endpoints of ours: `POST /api/v1/payments/uzum/{check,create,confirm,reverse,status}`.
We own the transaction state (`uzum_transactions.status`); Uzum signals a replay with its own
codes. Top-ups only in M3. Setup: [`kassa-setup.md`](./kassa-setup.md); reference:
`apps/api/src/csmarket/modules/uzum/README.md`; Postman collection for Uzum's engineer:
`docs/api/uzum.postman_collection.json`; design: ADR-0006.

## Quick checks

- **Uzum tile missing.** `CSMARKET_UZUM_SERVICE_ID` and one whole login/password pair must
  be set. `curl -s https://api.csmarket.uz/api/v1/payments/providers`.
- **HTTP 400 is normal.** Every error, including a replay, is HTTP 400 with
  `{"status": "FAILED", "errorCode"}`. A raw 500 or a non-JSON answer is the real signal.
- **Amount not prefilled in Uzum's app.** The checkout link's `order=` and the cabinet
  attribute name differ — [`kassa-setup.md`](./kassa-setup.md#uzum). The callbacks still
  work.

## Customer paid, balance not credited

1. Get the top-up number (`T…`) from the customer (their status page address) or their admin
   card («Пополнения»).
2. Admin → «Платежи» → search the number → open the Uzum attempt → «Транзакции кассы»
   (`external_id` = Uzum's `transId`; the payer's phone shows masked).
3. Read the Uzum row:
   - **none** — `/create` never reached us or was refused: auth (10001), service id (10006),
     not payable (10007 / 10008 / 10009 / 10011; `api` logs
     `uzum.callback endpoint=create code=… number=…`).
   - **`CREATED` (создана)** — Uzum has not confirmed. After 30 min our sweep fails it.
   - **`CONFIRMED` (подтверждён)** — paid and credited: attempt «оплачен», top-up
     «зачислено». Ask the customer to reload.
   - **`FAILED` (не прошла)** — no money taken by us: the 30-min sweep, or a second charge we
     refused (below).
   - **`REVERSED` (возвращена)** — cancelled before confirm (no money moved) or refunded after
     it (the top-up «отменено кассой», balance back).
4. If Uzum's side disagrees with ours, Uzum polls `/status` (up to 10 times) after a
   `/confirm` whose answer it lost. `/confirm` commits before it answers, so `/status` always
   sees `CONFIRMED`; repeated `/status` calls are expected traffic.
5. Never credit by hand in the database. If money truly reached us without a credit, use the
   admin balance adjustment with a reason that names the number (`wallet.md`), and tell the
   owner.

## Refunds from Uzum's side

There is no refund from our admin. Uzum calls `/reverse`:

- the amount is still on the balance → `REVERSED`, ledger `topup_reversal`, the top-up
  «отменено кассой»;
- the balance no longer covers it (spent) → **10017**, nothing changes
  (`payments.topup.reverse_refused number= amount=`); settle with the owner by hand.

## Auth (10001)

- The header must be `Authorization: Basic base64(login:password)` and match the production
  **or** the sandbox pair. A pair with a blank half never matches. In prod the sandbox pair
  counts only while `CSMARKET_KASSA_SANDBOX_ENABLED=true` (sandbox pass;
  [`kassa-setup.md`](./kassa-setup.md)); after go-live a sandbox call is 10001 by design.
- 10001 on every call means a pair in `secrets/api.env` differs from what Uzum sends, or is
  blank after a deploy. The alert `KassaRejectionsSpike` (`reason="auth"`) fires on it.
- A 10001 answer carries no `serviceId` / `transId`: auth is checked before the body is read.
- 10006 is different: the pair is right, but `serviceId` is not `CSMARKET_UZUM_SERVICE_ID`.

## Error codes

| Code  | Meaning                                              | Action                                                                                      |
| ----- | ---------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| 10001 | Basic auth failed                                    | Auth above                                                                                  |
| 10002 | Body is not a JSON object (or nested too deeply)     | A proxy mangling the body, or probing                                                       |
| 10003 | Not POST                                             | Not Uzum; a stray caller                                                                    |
| 10005 | A required field missing or mistyped                 | Compare with the Postman collection; the attribute must be `order` / `orderId` / `order_id` |
| 10006 | `serviceId` not ours                                 | The service id in env vs Uzum's                                                             |
| 10007 | Unknown top-up number                                | A broken link or a typo in the number                                                       |
| 10008 | Already paid; at `/confirm`, a second charge refused | Second charge below                                                                         |
| 10009 | Top-up expired or reversed                           | The customer starts a new top-up                                                            |
| 10010 | `transId` already created                            | Uzum's replay signal; harmless                                                              |
| 10011 | Amount is not the top-up's × 100 (tiyin)             | A soʻm amount sent as tiyin                                                                 |
| 10014 | Unknown `transId`                                    | Did `/create` land?                                                                         |
| 10015 | `/confirm` on a reversed or failed transaction       | It was closed first (sweep or reverse)                                                      |
| 10016 | `/confirm` replay                                    | Harmless                                                                                    |
| 10017 | `/reverse` of a top-up whose money was spent         | Refunds above                                                                               |
| 10018 | `/reverse` replay                                    | Harmless                                                                                    |
| 99999 | Internal error or a failed commit                    | `api` logs `uzum.merchant.internal_error`                                                   |

## Second charge refused

A retried checkout, or a top-up already paid through Click / Payme, can leave a second Uzum
transaction on a credited top-up. Its `/confirm` answers 10008 and the row is committed as
`FAILED`, so Uzum does not take the money twice and `/status` reports `FAILED`. Log:
`uzum.confirm.second_charge_refused number= amount=`.

## Timeout sweep

Scheduler job `uzum.timeout`, every 5 min (first run 200 s after start): `CREATED` rows older
than 30 min become `FAILED` and their attempt is released (only if no other `CREATED` row
holds it). Logs: `uzum.timeout.done count=`, `uzum.timeout.row_failed`,
`uzum.timeout.crashed`.

A `CONFIRMED` row is never swept, and a settled attempt is never cancelled. Seeing either is a
bug: stop and escalate.

## Never

- Never credit a balance in SQL or insert ledger rows by hand; use the admin adjustment with a
  reason (`wallet.md`).
- Never change a `uzum_transactions` row by hand: `/status` reads it.
- Never copy `payment_source` (it holds the payer's phone) into chat, a ticket or a log.
- Never paste a password into chat or a ticket; delete the sandbox pair after go-live.
