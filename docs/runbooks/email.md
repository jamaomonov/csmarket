# Runbook — Email (Resend)

Order letters (receipt, trade sent, refunded) and the email confirmation are written to the
`email_outbox` table in the transaction of their event and sent by the worker's `emails`
queue through Resend. Design: ADR-0008. Code: `apps/api/src/csmarket/modules/notifications/`.
A letter that fails never touches money or an order.

## Failing

Alert `EmailsFailing`: a letter was rejected by Resend or ran out of its six attempts
(1, 5, 15, 60, 180, 600 minutes apart) in the last 30 minutes.

1. See which rows failed and why (the code, never the provider's text):
   `select kind, last_error_code, count(*) from email_outbox where status = 'failed' and updated_at > now() - interval '1 day' group by 1, 2;`
2. `http_401` / `http_403` / `no_key`: the key is wrong or missing — check
   `CSMARKET_RESEND_API_KEY` in `secrets/api.env` and the key's permissions in Resend.
   Restart the worker with `IMAGE_TAG` pinned (`docs/runbooks/deploy.md`).
3. `http_422`: Resend refused the letter — usually the sending domain is not verified
   (SPF / DKIM records in Cloudflare) or the address is invalid. One row with a bad address
   needs nothing.
4. `timeout` / `network` / `http_5xx` after six attempts: Resend was unreachable for hours —
   check status.resend.com and the worker's egress.
5. To send failed letters again once the cause is fixed (letters only, no money moves):
   `update email_outbox set status = 'pending', attempts = 0, next_attempt_at = now() where status = 'failed' and updated_at > now() - interval '1 day';`
   Ask the owner first: a receipt a day late may confuse more than it helps.
