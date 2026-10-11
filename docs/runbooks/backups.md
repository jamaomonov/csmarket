# Backups (Postgres → age → Cloudflare R2)

The database is dumped every night, encrypted, and stored off the server. Live since
2026-10-11 (M5).

## What runs

- **Service:** `backup` in `docker-compose.prod.yml`, profile `ops`
  (`COMPOSE_PROFILES=alerts,ops` in `~/opt/csmarket/.env`).
- **When:** `infra/backup/run_nightly.sh` sleeps until `BACKUP_HOUR_UTC` (02:00 UTC = 07:00
  Tashkent), then runs `infra/backup/pg_backup.sh`:
  1. `pg_dump --format=custom`;
  2. `age --encrypt` to `BACKUP_AGE_RECIPIENT`;
  3. `rclone copyto r2:csmarket-backup/<YYYY-MM-DD>/csmarket-<timestamp>.dump.age`.

  4. `tar` of `secrets/` (all the server's env files) → `age` →
     `rclone rcat …/<YYYY-MM-DD>/secrets-<timestamp>.tar.age`, streamed.

  The plaintext dump never stays on disk, and the plaintext tar never touches it.

- **Proof of success:** after the upload, the script writes
  `csmarket_backup_last_success_timestamp_seconds` (and `csmarket_backup_last_size_bytes`)
  to the `backup-metrics` volume. node-exporter's textfile collector exports them.
- **Settings:** `secrets/backup.env`:
  - `PG*` — the same user and password as `secrets/postgres.env`;
  - `BACKUP_AGE_RECIPIENT`;
  - `RCLONE_REMOTE=r2:csmarket-backup`;
  - `RCLONE_CONFIG_R2_*` — the R2 endpoint of the account, plus the access key of an R2 API token
    with Object Read & Write on `csmarket-backup` only.

## The decryption key

The age **private** key is `~/csmarket-backup.key` on the owner's laptop. It was generated
2026-10-11, and its public half is `age1xv8x…zkzjz`. Keep a second copy in the owner's password
manager.

**It is never stored on the server:** a server that can read its own backups gives a thief
both. Lose the key and no backup can be read; there is no recovery.

## Alerts

- **`BackupStale`** (page) — no successful backup for 26 h.
  - Read `docker logs csmarket-prod-backup-1`; a failed night logs `NIGHTLY RUN FAILED`.
  - Usual causes: an R2 token revoked or expired (`AccessDenied`); `PGPASSWORD` out of sync with
    `postgres.env`; the disk full (`DiskSpaceLow`).
  - Fix it, then run one by hand (below).
- **`BackupNeverRan`** (page) — no timestamp for 27 h. Usual causes:
  - the `backup` service is not running (`ops` missing from `COMPOSE_PROFILES`);
  - node-exporter lacks the `backup-metrics` volume;
  - no run has succeeded since the deploy.

## Run one now

```bash
cd ~/opt/csmarket
docker compose -f docker-compose.prod.yml run --rm backup /bin/bash /scripts/pg_backup.sh
```

## Restore drill (no production write)

This is how the first backup was proven on 2026-10-11: 36 tables, and `users` / `orders` /
`skin_items` / `wallet_postings` / `alembic_version` equal to production.

1. **Fetch the file** to the laptop:
   ```bash
   ssh deploy@57.131.198.69 'cd ~/opt/csmarket && docker compose -f docker-compose.prod.yml run --rm -T --entrypoint sh backup -c "apk add --no-cache rclone >/dev/null; rclone cat r2:csmarket-backup/<date>/<file>.dump.age"' > b.dump.age
   ```
2. **Decrypt** with the private key, on the laptop:
   `age --decrypt -i ~/csmarket-backup.key -o b.dump b.dump.age`.
3. **Restore into a throwaway Postgres 16** and compare counts with production:
   ```bash
   docker run -d --rm -e POSTGRES_PASSWORD=x -e POSTGRES_DB=restore \
     -v "$PWD:/r" mirror.gcr.io/library/postgres:16-alpine
   pg_restore -U postgres -d restore --no-owner --no-privileges /r/b.dump   # inside it
   ```
4. **Clean up:** stop the container, then delete `b.dump` and `b.dump.age`.

Repeat it after a schema-heavy release and at least once a quarter.

## Getting the secrets back (a lost server)

Fetch the newest `secrets-*.tar.age` the same way as a dump (step 1 above), then on the
laptop:

```bash
age --decrypt -i ~/csmarket-backup.key secrets.tar.age | tar -xf - -C ./secrets
```

Copy them to the new server's `~/opt/csmarket/secrets/` with `chmod 600`, and delete the laptop
copy. The VPS IP changes with a new server, so update it in the supplier whitelists (Waxpeer,
Skinslink, LIS-SKINS).

## Restoring production (a real incident)

`make restore file=… identity=…` (`infra/backup/restore.sh`) replaces the live database. Ask
the owner first; it drops data written after the dump. The private key goes to the server only
for that run, in `/dev/shm`, and is deleted after.

## Storage

Each nightly file is about 60 MB (2026-10-11). Set an R2 Object Lifecycle Rule on
`csmarket-backup` to delete objects older than 30 days, in the Cloudflare dashboard under the
bucket's Settings → Object Lifecycle Rules. That keeps the bucket at about 2 GB, inside R2's
free 10 GB.
