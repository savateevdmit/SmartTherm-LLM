#!/usr/bin/env bash
set -euo pipefail

: "${DB_HOST:?DB_HOST is required}"
: "${DB_PORT:=3306}"
: "${DB_USER:?DB_USER is required}"
: "${DB_PASSWORD:?DB_PASSWORD is required}"
: "${DB_NAME:?DB_NAME is required}"

: "${BACKUP_DIR:=/backups}"
: "${RESTORE_FORCE:=0}"

export MYSQL_PWD="${DB_PASSWORD}"

echo "[db_restore] waiting for db ${DB_HOST}:${DB_PORT}..."
for i in $(seq 1 60); do
  if mariadb -h"${DB_HOST}" -P"${DB_PORT}" -u"${DB_USER}" -e "SELECT 1" >/dev/null 2>&1; then
    echo "[db_restore] db is ready"
    break
  fi
  sleep 2
done

mariadb -h"${DB_HOST}" -P"${DB_PORT}" -u"${DB_USER}" -e "SELECT 1" >/dev/null

echo "[db_restore] ensuring database exists: ${DB_NAME}"
mariadb -h"${DB_HOST}" -P"${DB_PORT}" -u"${DB_USER}" -e "CREATE DATABASE IF NOT EXISTS \`${DB_NAME}\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"

tables_count() {
  mariadb -N -s -h"${DB_HOST}" -P"${DB_PORT}" -u"${DB_USER}" \
    -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='${DB_NAME}';"
}

before="$(tables_count)"
echo "[db_restore] tables in ${DB_NAME} before restore: ${before}"

if [[ "${RESTORE_FORCE}" != "1" && "${before}" != "0" ]]; then
  echo "[db_restore] skip restore: database is not empty"
  exit 0
fi

latest="$(find "${BACKUP_DIR}" -maxdepth 1 -type f -name "*.sql.gz" -size +100k -print0 2>/dev/null | xargs -0 ls -1t 2>/dev/null | head -n 1 || true)"
if [[ -z "${latest}" ]]; then
  echo "[db_restore] no valid backups found in ${BACKUP_DIR} (need *.sql.gz >100KB), nothing to restore"
  exit 0
fi

log_file="${BACKUP_DIR}/restore_last.log"
echo "[db_restore] restoring from ${latest} ..."
echo "[db_restore] writing import log to ${log_file}"

set +e
gzip -dc "${latest}" | mariadb -h"${DB_HOST}" -P"${DB_PORT}" -u"${DB_USER}" "${DB_NAME}" 1>"${log_file}" 2>&1
rc=$?
set -e

echo "[db_restore] import exit_code=${rc}"

after="$(tables_count)"
echo "[db_restore] tables in ${DB_NAME} after restore: ${after}"

if [[ "${after}" == "0" ]]; then
  echo "[db_restore] ERROR: no tables created after import."
  echo "[db_restore] Last 120 lines of import log:"
  tail -n 120 "${log_file}" || true
  exit 2
fi

echo "[db_restore] restore finished successfully"