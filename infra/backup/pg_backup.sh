#!/usr/bin/env bash
# Nightly Postgres backup: pg_dump -> age -> rclone -> Cloudflare R2.
# Expected env vars (mounted via secrets/backup.env):
#   PGHOST=postgres
#   PGUSER=...
#   PGPASSWORD=...
#   PGDATABASE=csmarket
#   BACKUP_AGE_RECIPIENT=age1...
#   RCLONE_REMOTE=r2:csmarket-backups

set -euo pipefail

date_dir="$(date -u +%Y-%m-%d)"
file_ts="$(date -u +%FT%H-%M-%SZ)"
tmp_dir="${TMPDIR:-/tmp/backup}"
mkdir -p "$tmp_dir"

dump="${tmp_dir}/csmarket-${file_ts}.dump"
enc="${dump}.age"
# Never leave the plaintext dump (or a partial .age) behind on any exit —
# a failed encrypt or upload must not park an unencrypted copy of the database
# in the backup-tmp volume.
trap 'rm -f "$dump" "$enc"' EXIT

echo "[backup] dumping ${PGDATABASE} ..."
pg_dump --format=custom --no-owner --no-privileges --file "$dump"

echo "[backup] encrypting ..."
age --encrypt --recipient "$BACKUP_AGE_RECIPIENT" --output "$enc" "$dump"
rm -f "$dump"

echo "[backup] uploading to ${RCLONE_REMOTE}/${date_dir}/ ..."
rclone copyto "$enc" "${RCLONE_REMOTE}/${date_dir}/$(basename "$enc")"

size="$(stat -c %s "$enc" 2>/dev/null || wc -c <"$enc")"
rm -f "$enc"

# The server's env files, encrypted to the same key, beside the dump: a lost server must not
# take the provider keys with it. Streamed — the plaintext tar never touches the disk. The
# bucket's 30-day lifecycle rule would delete a one-off copy, hence every night.
secrets_dir="${BACKUP_SECRETS_DIR:-/secrets}"
if [ -d "$secrets_dir" ]; then
  echo "[backup] uploading the encrypted secrets ..."
  tar -C "$secrets_dir" -cf - . |
    age --encrypt --recipient "$BACKUP_AGE_RECIPIENT" |
    rclone rcat "${RCLONE_REMOTE}/${date_dir}/secrets-${file_ts}.tar.age"
fi

# For Prometheus (node-exporter's textfile collector): the alert BackupStale fires when this
# timestamp is older than 26 h. Written atomically, and only after a successful upload.
metrics_dir="${BACKUP_METRICS_DIR:-/metrics}"
if [ -d "$metrics_dir" ]; then
  {
    echo "# HELP csmarket_backup_last_success_timestamp_seconds When the last backup reached R2."
    echo "# TYPE csmarket_backup_last_success_timestamp_seconds gauge"
    echo "csmarket_backup_last_success_timestamp_seconds $(date -u +%s)"
    echo "# HELP csmarket_backup_last_size_bytes Size of the last encrypted backup."
    echo "# TYPE csmarket_backup_last_size_bytes gauge"
    echo "csmarket_backup_last_size_bytes ${size}"
  } >"${metrics_dir}/csmarket_backup.prom.tmp"
  mv "${metrics_dir}/csmarket_backup.prom.tmp" "${metrics_dir}/csmarket_backup.prom"
fi
echo "[backup] done"
