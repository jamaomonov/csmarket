# Runbook — Email (Resend)

Order letters (receipt, trade sent, refunded) and the email confirmation are written to the
`email_outbox` table in the transaction of their event and sent by the worker's `emails`
queue through Resend. Design: ADR-0008. Code: `apps/api/src/csmarket/modules/notifications/`.
A letter that fails never touches money or an order: the order page always tells the buyer
everything.

## Setup (owner, once)

1. In Resend, add the domain `csmarket.uz` and put the SPF and DKIM records it shows into
   Cloudflare DNS (DNS only, not proxied). Wait for «Verified».
2. Create an API key with **sending access** to that domain only.
3. On the server, in `secrets/api.env`: `CSMARKET_EMAIL_TRANSPORT=resend`,
   `CSMARKET_RESEND_API_KEY=<key>`; the sender defaults to
   `CS Market <noreply@csmarket.uz>` (`CSMARKET_EMAIL_FROM`, `CSMARKET_EMAIL_FROM_NAME`).
   Restart the API and the worker with `IMAGE_TAG` pinned (`deploy.md`). The API logs a
   start-up warning naming any missing prod setting.

A key pasted into a chat is never stored anywhere — rotate it in Resend.

## The outbox

```sql
-- what is waiting, and what gave up, today
select kind, status, count(*) from email_outbox
 where created_at > now() - interval '1 day' group by 1, 2 order by 1, 2;
-- one order's letters
select kind, status, attempts, last_error_code, sent_at from email_outbox
 where order_id = (select id from orders where number = 'AB12CD34');
```

Statuses: `pending` (due at `next_attempt_at`), `sent`, `skipped` (no verified address at send
time — never retried), `failed` (rejected, or six attempts 1, 5, 15, 60, 180, 600 minutes
apart). `last_error_code` is ours (`http_422`, `timeout`, `network`, `no_key`…), never the
provider's text. Rows hold no address except `verify` rows, whose address the nightly
erase drops after 7 days.

## Failing

Alert `EmailsFailing`: a letter was rejected by Resend or ran out of its six attempts in the
last 30 minutes.

1. See which rows failed and why:
   `select kind, last_error_code, count(*) from email_outbox where status = 'failed' and updated_at > now() - interval '1 day' group by 1, 2;`
2. `http_401` / `http_403` / `no_key`: the key is wrong or missing — check
   `CSMARKET_RESEND_API_KEY` and the key's permissions in Resend; restart with `IMAGE_TAG`.
3. `http_422`: Resend refused the letter — usually the domain is not verified (SPF / DKIM in
   Cloudflare) or the address is invalid. One row with a bad address needs nothing.
4. `timeout` / `network` / `http_5xx` after six attempts: Resend was unreachable for hours —
   check status.resend.com and the worker's egress.
5. To send failed letters again once the cause is fixed (letters only, no money moves):
   `update email_outbox set status = 'pending', attempts = 0, next_attempt_at = now() where status = 'failed' and updated_at > now() - interval '1 day';`
   Ask the owner first: a receipt a day late may confuse more than it helps.

## «Письмо не пришло»

1. Is the buyer's email confirmed? (Admin user card, or
   `select email_verified_at is not null from users where steam_id = '…'` — do not paste the
   address into chats.) Unconfirmed → order letters are `skipped` by design (D1); ask them to
   confirm from the profile («Отправить ещё раз»).
2. The order's rows (query above): `sent` → ask them to check spam and the «Промоакции» tab;
   `skipped` → not confirmed or the address changed after the order; `pending` → the worker
   is behind or Resend is down (`EmailsFailing`, worker logs `notifications.email`).
3. A confirmation link that «не подходит»: it is for an older address or older than 24 h —
   they send it again from the profile.

## Changing the sender

Set `CSMARKET_EMAIL_FROM` (an address on the verified domain) and
`CSMARKET_EMAIL_FROM_NAME`, restart the worker with `IMAGE_TAG`. A new domain needs the
Setup steps first.

## Locally

`CSMARKET_EMAIL_TRANSPORT=dev` (the default): letters go to Redis
(`notifications:dev:mail`, last 50, 1 h) and a signed-in user reads their own through
`GET /api/v1/dev/emails?kind=verify`. No Resend key is needed.
