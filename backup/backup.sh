#!/bin/sh
# Nightly backup of the Christmas app: a pg_dump of the database plus a tarball
# of uploads/assignments. Runs in the "backup" service from docker-compose.yml.
#
#   Back up right now:   docker compose exec backup sh /backup.sh once
#   Restore a database:  see README.md ("Backups & restore")

BACKUP_DIR=/backups
KEEP_DAYS="${BACKUP_KEEP_DAYS:-14}"
INTERVAL="${BACKUP_INTERVAL_SECONDS:-86400}"

run_backup() {
    stamp=$(date +%Y%m%d-%H%M%S)
    mkdir -p "$BACKUP_DIR"

    # Write to a temp name and only rename once complete, so a half-written
    # file is never mistaken for a good backup
    if pg_dump -h db -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f "$BACKUP_DIR/.db-$stamp.tmp"; then
        mv "$BACKUP_DIR/.db-$stamp.tmp" "$BACKUP_DIR/db-$stamp.dump"
        echo "[backup] database -> db-$stamp.dump"
    else
        rm -f "$BACKUP_DIR/.db-$stamp.tmp"
        echo "[backup] ERROR: pg_dump failed" >&2
    fi

    if tar -czf "$BACKUP_DIR/.files-$stamp.tmp" -C /app-data .; then
        mv "$BACKUP_DIR/.files-$stamp.tmp" "$BACKUP_DIR/files-$stamp.tar.gz"
        echo "[backup] uploads/assignments -> files-$stamp.tar.gz"
    else
        rm -f "$BACKUP_DIR/.files-$stamp.tmp"
        echo "[backup] ERROR: file archive failed" >&2
    fi

    find "$BACKUP_DIR" -maxdepth 1 \( -name 'db-*.dump' -o -name 'files-*.tar.gz' \) \
        -mtime +"$KEEP_DAYS" -delete
}

if [ "$1" = "once" ]; then
    run_backup
    exit 0
fi

# Exit promptly on "docker compose down"
trap 'exit 0' TERM INT

# Wait for the database, back up immediately on start, then on an interval
until pg_isready -h db -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null 2>&1; do
    sleep 5
done
while true; do
    run_backup
    sleep "$INTERVAL" &
    wait $!
done
