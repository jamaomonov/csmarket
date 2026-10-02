# Runbook — Payme (Merchant API)

Payme calls one JSON-RPC endpoint of ours over the life of a transaction:
`POST /api/v1/payments/payme/merchant` (CheckPerform, Create, Perform, Cancel, Check,
GetStatement, SetFiscalData). Our row in `payme_transactions` mirrors Payme's transaction.
Top-ups only in M3. Setup: [`kassa-setup.md`](./kassa-setup.md); reference:
`apps/api/src/csmarket/modules/payme/README.md`; design: ADR-0006.

## Quick checks

- **Payme tile missing.** `CSMARKET_PAYME_MERCHANT_ID` and `CSMARKET_PAYME_KEY` must be set.
  In prod `CSMARKET_PAYME_TEST_KEY` counts only while `CSMARKET_KASSA_SANDBOX_ENABLED=true`
  (sandbox pass; [`kassa-setup.md`](./kassa-setup.md)).
  `curl -s https://api.csmarket.uz/api/v1/payments/providers`.
- **Sandbox suite gets −32504 in prod.** Prod ignores the test key unless
  `CSMARKET_KASSA_SANDBOX_ENABLED=true`; after go-live that is the intended answer.
- **Always HTTP 200** with `{result}` or `{error}`. A bare **403** (no JSON body) is Caddy's
  IP allowlist (`185.234.113.0/28`), not the app — see
  [`kassa-setup.md#rejections`](./kassa-setup.md#rejections). A test from any other network
  403s by design. Confirm with Payme which addresses its sandbox calls from: if they are
  outside `185.234.113.0/28`, widen the allowlist for the sandbox pass only.
- **Wrong checkout host.** The sandbox needs `CSMARKET_PAYME_CHECKOUT_URL=https://test.paycom.uz`;
  production must not have it (default `checkout.paycom.uz`).

## Customer paid, balance not credited

1. Get the top-up number (`T…`) from the customer (their status page address) or their admin
   card («Пополнения»).
2. Admin → «Платежи» → search the number → open the Payme attempt → «Транзакции кассы».
3. Read the Payme row (`external_id` = Payme's transaction id; find the same id in the Payme
   cabinet to compare both sides):
   - **none** — CreateTransaction never reached us or was refused: the Caddy 403 above, auth
     (−32504), or not payable (−31050 / −31051 / −31001; `api` logs
     `payme.rpc method=CreateTransaction code=… number=…`).
   - **`created` (создана, state 1)** — Payme has not called Perform. The customer did not
     finish, or Perform failed on Payme's side. After 12 h our sweep cancels it (reason 4).
   - **`performed` (проведена, state 2)** — paid and credited: attempt «оплачен», top-up
     «зачислено». Ask the customer to reload.
   - **`cancelled` (отменена, state −1)** — no money taken: Payme cancelled it (reason 2 = the
     card was declined), the 12 h sweep (reason 4), or a second charge we refused (reason 3,
     below).
   - **`cancelled_after_perform` (отменена после проведения, state −2)** — refunded from the
     Payme cabinet; the top-up is «отменено кассой» and the balance went back.
4. Never credit by hand in the database. If money truly reached us without a credit, use the
   admin balance adjustment with a reason that names the number (`wallet.md`), and tell the
   owner.

## Refunds from the Payme cabinet

There is no refund from our admin. An operator cancels the transaction in the Payme
cabinet; Payme calls our CancelTransaction:

- the amount is still on the balance → state −2, ledger `topup_reversal`, the top-up
  «отменено кассой», the customer's history «Пополнение отменено»;
- the balance no longer covers it (the money was spent) → **−31007**, nothing changes
  (`payments.topup.reverse_refused number= amount=`). The refund cannot go through us; settle
  it with the owner by hand.

## Error codes

| Code   | Meaning                                                                                             | Action                                                             |
| ------ | --------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------ |
| −31001 | Amount is not the top-up's × 100 (tiyin)                                                            | A soʻm amount or a tampered link; the customer starts a new top-up |
| −31003 | Unknown transaction id                                                                              | Did CreateTransaction land? Check reachability                     |
| −31007 | Cancel of a performed top-up whose money was spent                                                  | Refunds above                                                      |
| −31008 | Perform on a cancelled transaction; a second charge; another account                                | Second charge below; otherwise check the row's state               |
| −31050 | `account.order` missing or unknown                                                                  | A broken link, or the cabinet field is not named `order`           |
| −31051 | Top-up paid, expired or reversed; an order cancelled (at Perform too: the transaction is cancelled) | The customer starts a new top-up or order                          |
| −31099 | Another live Payme transaction holds the top-up                                                     | Payme's rule; the earlier one finishes or times out                |
| −32001 | SetFiscalData for an unknown transaction                                                            | As −31003                                                          |
| −32300 | Not POST                                                                                            | Not Payme; a stray caller                                          |
| −32400 | Internal error or a failed commit                                                                   | `api` logs `payme.merchant.internal_error`; Payme retries          |
| −32504 | Basic auth failed                                                                                   | The key in `secrets/api.env` vs the cabinet; alert `reason="auth"` |
| −32600 | Bad envelope or a mistyped parameter                                                                | Not Payme's normal traffic; check the caller                       |
| −32601 | Unknown method                                                                                      | —                                                                  |
| −32700 | Body is not JSON (or over 64 KiB, or nested too deeply)                                             | A proxy mangling the body, or probing                              |

Payme shows the customer «Сервис поставщика услуг недоступен» on −32400. A retry after a
declined card opens a new attempt (`payme:<number>:<id>`), so a retry is never −32400 by
design; if one happens, read the `internal_error` stack trace.

## Second charge refused

A retried checkout, or a top-up already paid through Click / Uzum, can leave a second Payme
transaction on a credited top-up. Its PerformTransaction answers −31008 and the transaction
is committed as cancelled (state −1, reason 3), so Payme does not take the money twice. Log:
`payme.perform.second_charge_refused number= amount=`.

## Timeout sweep

Scheduler job `payme.timeout`, every 5 min (first run 180 s after start): state-1 rows older
than 12 h become −1, reason 4, and their attempt is released (only if no other state-1 row
holds it). Logs: `payme.timeout.done count=`, `payme.timeout.row_failed`,
`payme.timeout.crashed`.

A PerformTransaction on a state-1 transaction older than 12 h that the sweep has not reached
yet still settles: the customer paid, so they get the credit; the sweep runs every 5 min, so
the window is small.

A performed (state 2) row is never swept, and a settled attempt is never cancelled. Seeing
either is a bug: stop and escalate.

## Never

- Never credit a balance in SQL or insert ledger rows by hand; use the admin adjustment with a
  reason (`wallet.md`).
- Never change a `payme_transactions` row by hand: Payme's CheckTransaction reads it.
- Never paste a key into chat or a ticket; delete the test key after go-live.
