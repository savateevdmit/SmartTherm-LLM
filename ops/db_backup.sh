#!/usr/bin/env bash
set -euo pipefail

: "${DB_HOST:?DB_HOST is required}"
: "${DB_PORT:=3306}"
: "${DB_USER:?DB_USER is required}"
: "${DB_PASSWORD:?DB_PASSWORD is required}"
: "${DB_NAME:?DB_NAME is required}"

: "${BACKUP_DIR:=/backups}"
: "${BACKUP_INTERVAL_HOURS:=72}"
: "${BACKUP_KEEP_DAYS:=30}"

mkdir -p "${BACKUP_DIR}"

# Prefer mariadb-dump if available, fallback to mysqldump
DUMP_BIN=""
if command -v mariadb-dump >/dev/null 2>&1; then
  DUMP_BIN="mariadb-dump"
elif command -v mysqldump >/dev/null 2>&1; then
  DUMP_BIN="mysqldump"
else
  echo "[db_backup] ERROR: neither mariadb-dump nor mysqldump found in container"
  echo "[db_backup] TIP: use image mariadb:11 or mysql:8 that includes dump client"
  exit 1
fi

echo "[db_backup] started. dump_bin=${DUMP_BIN} interval=${BACKUP_INTERVAL_HOURS}h keep=${BACKUP_KEEP_DAYS}d dir=${BACKUP_DIR}"

export MYSQL_PWD="${DB_PASSWORD}"

while true; do
  ts="$(date -u +%Y%m%d_%H%M%S)"
  out="${BACKUP_DIR}/${DB_NAME}_${ts}.sql.gz"

  echo "[db_backup] dumping to ${out}"

  # --column-statistics=0 supported by mysqldump; mariadb-dump ignores unknown options? to be safe, pass only when mysqldump
  EXTRA_OPTS=()
  if [[ "${DUMP_BIN}" == "mysqldump" ]]; then
    EXTRA_OPTS+=(--column-statistics=0)
  fi

  "${DUMP_BIN}" \
    -h"${DB_HOST}" -P"${DB_PORT}" \
    -u"${DB_USER}" \
    --single-transaction --quick --routines --triggers \
    "${EXTRA_OPTS[@]}" \
    "${DB_NAME}" | gzip -c > "${out}"

  echo "[db_backup] cleanup older than ${BACKUP_KEEP_DAYS} days"
  find "${BACKUP_DIR}" -type f -name "*.sql.gz" -mtime "+${BACKUP_KEEP_DAYS}" -delete || true

  echo "[db_backup] sleeping ${BACKUP_INTERVAL_HOURS}h"
  sleep "$((BACKUP_INTERVAL_HOURS * 3600))"
done