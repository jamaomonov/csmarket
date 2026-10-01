#!/usr/bin/env bash
# Restore an encrypted Postgres dump (.dump.age) into PGDATABASE, replacing it.
#
# Run it through `make restore` on the server, not by hand:
#
#   make restore file=/path/to/csmarket-….dump.age identity=/dev/shm/csmarket-backup.key
#
# `identity` is the age PRIVATE key (AGE-SECRET-KEY-…). It lives offline on the
# operator's laptop and never stays on the server: copy it to RAM for the
# restore and delete it right after —
#
#   scp ~/csmarket-backup.key deploy@<VPS_IP>:/dev/shm/csmarket-backup.key
#   … make restore …
#   ssh deploy@<VPS_IP> 'shred -u /dev/shm/csmarket-backup.key'
#
# `make restore` mounts the key read-only at a fixed path and sets
# BACKUP_AGE_IDENTITY to it. Stop api, worker and scheduler first: DROP DATABASE
# refuses while they hold connections.
#
# Env: PGHOST, PGUSER, PGPASSWORD, PGDATABASE (secrets/backup.env),
#      BACKUP_AGE_IDENTITY (path to the private key file).

set -euo pipefail

src="${1:?usage: restore.sh <backup.dump.age>}"
identity="${BACKUP_AGE_IDENTITY:?BACKUP_AGE_IDENTITY must name the age private key file (see make restore)}"
[ -r "$identity" ] || { echo "[restore] cannot read identity file $identity" >&2; exit 1; }

# Busybox mktemp (alpine) wants the X-run at the very end of the template.
tmp_dump="$(mktemp /tmp/csmarket-restore-XXXXXX)"
trap 'rm -f "$tmp_dump"' EXIT

echo "[restore] decrypting ${src} ..."
age --decrypt --identity "$identity" --output "$tmp_dump" "$src"

echo "[restore] dropping & recreating ${PGDATABASE} ..."
# psql interpolates :"db" only in SQL it reads (stdin or -f), never in -c, so
# the statements are piped in. :"db" quotes the identifier server-side — a
# PGDATABASE with spaces/metacharacters can't break out of the statement.
printf 'DROP DATABASE IF EXISTS :"db";\n' |
  psql -X -v ON_ERROR_STOP=1 -v db="$PGDATABASE" -d postgres
printf 'CREATE DATABASE :"db";\n' |
  psql -X -v ON_ERROR_STOP=1 -v db="$PGDATABASE" -d postgres

echo "[restore] pg_restore ..."
pg_restore --no-owner --no-privileges --dbname "$PGDATABASE" "$tmp_dump"

echo "[restore] done"
