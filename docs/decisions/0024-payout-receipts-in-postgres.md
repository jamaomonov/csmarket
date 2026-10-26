# 0024. Payout receipts in Postgres

- **Status**: Accepted
- **Date**: 2026-10-26
- **Deciders**: owner
- **Tags**: backend | data | infra

## Context and problem statement

An admin pays a card payout by hand from a bank app. When a seller says the money never came,
the admin needs the proof at hand: the bank's screenshot or PDF of the transfer. The owner wants
an optional upload of up to three such files on a paid payout, seen by admins only, and a wrong
one removable for a short while (2026-10-26). Until now the project stored no files at all.

## Decision drivers

- The proof must outlive the server: it is what settles a dispute months later.
- No new dependency or infra service for a handful of small files a day.
- The files are PII (a card, a name): admins only, no public link, nothing in the logs.

## Considered options

1. **Bytes in a Postgres table** (`payout_proofs.data`, deferred), sent as the raw request body.
2. **Cloudflare R2** (S3 API, the bucket the backups already use) with signed links.
3. **A Docker volume** on the VPS.

## Decision outcome

**Chosen option:** 1.

- The nightly `pg_dump` → age → R2 backup keeps the receipts with the payout they prove; nothing
  new to back up or restore.
- The upload is the file itself as the body, its name in `X-File-Name`: no multipart parser
  (`python-multipart` would be a new dependency). The API reads it in chunks and refuses it past
  5 MB; Caddy lets 6 MB through on that one path and keeps 1 MB everywhere else.
- The type is read from the bytes (JPG, PNG, WebP, PDF), never from the name or the header, so a
  served file is always what its `Content-Type` says (`nosniff`, `no-store`).
- The admin SPA fetches a receipt with its Bearer token and opens it as a `blob:` URL; there is
  no link that works without the session.
- Three per payout, only to a `paid` one; deletion within 10 minutes of the upload (the same
  window as «Вернуть в очередь»), then the file stays. The request row is locked on every write.

### Positive consequences

- No new dependency, no new external call, no new secret.
- Receipts are restored together with the rest of the data, in one step.

### Negative consequences

- The database and every backup grow by the receipts (a few hundred KB each; at 30 payouts a
  day about 10 MB a day at worst). Move them to R2 if this ever matters; the API need not change.
- A 5 MB body is held in the API's memory during the upload; uploads are admin-only and rare.

## Validation

`test_sales_admin_payout_proofs.py` (types, limits, the window, replay, admin-only) and
`test_sales_admin_proofs.py` (name cleaning, sniffing); backup size watched in `BackupStale`'s
runbook.
