#!/bin/bash
# Dump the whole database to a dated, gzipped archive in GCS.
# Required env: MONGODB_URI, BACKUP_BUCKET (e.g. gs://reliafy-backups).
set -euo pipefail

: "${MONGODB_URI:?MONGODB_URI is required}"
: "${BACKUP_BUCKET:?BACKUP_BUCKET is required}"

STAMP="$(date -u +%Y-%m-%d-%H%M)"
DEST="${BACKUP_BUCKET%/}/mongodump-${STAMP}.archive.gz"

echo "Dumping to ${DEST}…"
mongodump --uri "${MONGODB_URI}" --archive --gzip | gcloud storage cp - "${DEST}"

SIZE=$(gcloud storage ls -l "${DEST}" | awk 'NR==1 {print $1}')
if [ -z "${SIZE}" ] || [ "${SIZE}" -lt 1024 ]; then
  echo "ERROR: backup looks empty (${SIZE:-0} bytes)" >&2
  exit 1
fi
echo "Backup complete: ${DEST} (${SIZE} bytes)"
