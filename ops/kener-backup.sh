#!/bin/bash
# Nightly backup of the Kener database.
#
# Unlike Gatus, Kener keeps its MONITOR DEFINITIONS in the database, not in git
# -- losing the volume loses the configuration, not just the graphs. That is the
# whole reason this exists (F-001).
#
# Installed on the VM as /usr/local/bin/kener-backup.sh, run nightly by
# kener-backup.timer (see ops/ in this repo).
#
# KNOWN GAP: the dump lands on the VM's own OS disk, the same disk as the
# database volume. Losing that disk loses both. (On the old WSL host the dump
# went to C:, off the VHDX; that no longer applies.) An off-VM copy is pending.
set -uo pipefail
# Dumps and the log are readable by root only.
umask 077

DEST=/var/backups/kener
KEEP=14
CONTAINER=kener-postgres-1
STAMP=$(date -u +%Y%m%d-%H%M%S)
OUT="$DEST/kener-${STAMP}.dump"
LOG="$DEST/backup.log"

log() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $*" >> "$LOG"; }

if ! docker inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null | grep -q true; then
  log "FAIL container $CONTAINER is not running"
  exit 1
fi

# -Fc is the custom format: compressed, and restorable selectively with pg_restore.
if ! docker exec "$CONTAINER" pg_dump -U kener -d kener -Fc > "$OUT" 2>>"$LOG"; then
  log "FAIL pg_dump returned non-zero; removing partial $OUT"
  rm -f "$OUT"
  exit 1
fi

SIZE=$(stat -c %s "$OUT" 2>/dev/null || echo 0)
# A pg_dump custom-format file starts with the magic string "PGDMP". Checking it
# is the difference between "a file exists" and "a backup exists".
if [ "$SIZE" -lt 1024 ] || [ "$(head -c 5 "$OUT")" != "PGDMP" ]; then
  log "FAIL dump failed validation (size=$SIZE); removing $OUT"
  rm -f "$OUT"
  exit 1
fi

log "OK   $(basename "$OUT") ${SIZE} bytes"

# Retention: keep the newest $KEEP (two weeks of nightly dumps).
ls -1t "$DEST"/kener-*.dump 2>/dev/null | tail -n +$((KEEP + 1)) | while read -r old; do
  rm -f "$old" && log "PRUNE $(basename "$old")"
done
exit 0
