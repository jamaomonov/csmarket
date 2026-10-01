# Production secrets

`docker-compose.prod.yml` mounts env files from `./secrets/` — a git-ignored
directory next to it, inside the checkout on the server. **This folder is the
template**: copy each `.env` there, fill in real values, then `chmod 600` the lot.

The server holds the only copy. `/secrets/` is in `.gitignore` and the server's
deploy key is read-only, so these files cannot be pushed back — but that also
means nothing restores them for you. Keep an offline copy of whatever you cannot
regenerate (notably `CSMARKET_APP_ENC_KEY`: rotating it makes every encrypted row unreadable; from M1 also `CSMARKET_JWT_PRIVATE_KEY`: rotating it invalidates every live session).

## On the host (one-time)

```bash
cd ~/opt/csmarket          # the checkout
install -d -m 0700 secrets

# Copy the templates in, then fill in real values:
cp infra/secrets-example/*.env secrets/
$EDITOR secrets/postgres.env secrets/api.env secrets/caddy.env secrets/grafana.env secrets/backup.env
chmod 600 secrets/*.env

# Sanity check — must return nothing:
grep -RIn 'CHANGE_ME' secrets/
```

## What lives where

| File                    | Consumed by                                                                                   |
| ----------------------- | --------------------------------------------------------------------------------------------- |
| `postgres.env`          | `postgres` container — initial role/db creation                                               |
| `postgres-exporter.env` | `postgres-exporter` container (Prometheus scrape)                                             |
| `redis.env`             | `redis` (requirepass) + `redis-exporter`; password also goes into the Redis URLs in `api.env` |
| `api.env`               | `api`, `worker`, `scheduler` (all share the same runtime env)                                 |
| `web.env`               | `web` (Next.js storefront) — bundled into the JS, public                                      |
| `caddy.env`             | `caddy` — ACME email + Grafana basic-auth hash                                                |
| `grafana.env`           | `grafana` admin credentials                                                                   |
| `alertmanager.env`      | `alertmanager` — Telegram bot token + chat id for alerts                                      |
| `backup.env`            | nightly `pg_dump → age → rclone` pipeline                                                     |

## Generating the bits inside

### Strong random strings (passwords, app secrets)

```bash
openssl rand -base64 32 | tr -d '+/='
```

### JWT keypair (Ed25519, base64-PEM) — from M1

```bash
umask 077
openssl genpkey -algorithm Ed25519 -out priv.pem
# Private key (PKCS#8 PEM, base64-encoded one-liner)
base64 < priv.pem | tr -d '\n'; echo
# Public key
openssl pkey -in priv.pem -pubout | base64 | tr -d '\n'; echo
shred -u priv.pem 2>/dev/null || rm -P priv.pem
```

Put each into `CSMARKET_JWT_PRIVATE_KEY` / `CSMARKET_JWT_PUBLIC_KEY` in `api.env`
(M1 adds them to the template). The private key never leaves the server.

### AGE keypair for backup encryption

```bash
# On the operator's machine (NEVER on the production host):
brew install age   # or apt-get install age
age-keygen -o ~/csmarket-backup.key
# The "public key" line goes into backup.env as BACKUP_AGE_RECIPIENT.
# The "AGE-SECRET-KEY-…" line stays OFFLINE on your machine; you'll
# need it to decrypt a backup during restore.
```

### Grafana basic-auth hash

Caddy needs a bcrypt hash, not the plaintext password:

```bash
docker compose -f docker-compose.prod.yml run --rm --no-deps caddy \
  caddy hash-password --plaintext "the-real-password"
```

Paste the output into `GRAFANA_BASIC_AUTH_HASH` in `caddy.env`, with every `$` doubled to `$$`
(see the comment in that file).

### rclone remote (Cloudflare R2)

**Do not run `rclone config`.** The backup container mounts no `rclone.conf`, so a
remote configured on the host is invisible to it. The remote is defined by the
`RCLONE_CONFIG_R2_*` variables in `backup.env` instead — see that file.

Two things must be true on the Cloudflare side:

1. **The bucket exists.** R2 API tokens are object-scoped and cannot create buckets
   (`rclone mkdir` returns 403). Create `csmarket-backups` in the dashboard.
2. **The token's scope covers it.** A token issued for another bucket gets 403 on the
   backup bucket. Issue a separate token scoped to `csmarket-backups` only: any token
   the `api` / `worker` / `scheduler` containers hold is exposed to everything that
   compromises one of them, and sharing it would let that also delete the database backups.

Verify end to end rather than trusting a green log line:

```bash
docker compose -f docker-compose.prod.yml exec -T backup bash /scripts/pg_backup.sh
docker compose -f docker-compose.prod.yml exec -T backup rclone ls r2:csmarket-backups
# Then restore-test it — see docs/runbooks/restore-from-backup.md.
```

## Validation

Before the first `docker compose up`, sanity-check that nothing still
says `CHANGE_ME`:

```bash
cd ~/opt/csmarket
grep -RIn 'CHANGE_ME' secrets/  # must return nothing
```

## Applying a changed secret

**`docker compose restart` does not do it.** Compose reads `env_file` when it _creates_ a
container; `restart` reuses the existing one, so the process comes back with the old values and
nothing tells you. Verified on the box: after editing `api.env`, `restart` left the container id
unchanged and the new variable absent, while `up -d` replaced the container and picked it up.

Use `up -d` (it recreates any service whose config hash changed):

```bash
docker compose -f docker-compose.prod.yml up -d api worker scheduler
```

Then confirm the value actually landed, rather than assuming:

```bash
docker compose -f docker-compose.prod.yml exec -T api printenv CSMARKET_BASE_URL
```

## Rotation

When a credential is compromised:

1. Generate the replacement (see sections above).
2. Update the relevant `.env`.
3. Apply it with `up -d` as above — **not** `restart`.
4. For Postgres password changes, `ALTER ROLE csmarket_app WITH PASSWORD '…'` **first**, then
   update `postgres.env`, `postgres-exporter.env`, `backup.env` and the `CSMARKET_DATABASE_URL` in
   `api.env` — they all carry the same password, and a half-rotated set takes the API down.

## sops + age (M5)

The owner's age key is generated at launch; from then on `secrets/*.enc.env` may be committed
encrypted and decrypted on the server with `sops -d`. Until then the server holds the only copy.
