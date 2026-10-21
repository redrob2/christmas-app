#!/bin/sh
# Starts the whole app in one container:
#   1. as root: create the data folders and hand them to PUID:PGID (Unraid: 99:100)
#   2. as that user: prepare the database once (tables, upgrades, keys, setup code)
#   3. the daily reminder scheduler in the background (restarted if it ever stops)
#   4. the web server in the foreground
set -e

DATA_PATH="${DATA_PATH:-/app/data}"
export DATA_PATH

if [ "$(id -u)" = "0" ]; then
    PUID="${PUID:-99}"
    PGID="${PGID:-100}"
    mkdir -p "$DATA_PATH/uploads/profiles" "$DATA_PATH/uploads/items" "$DATA_PATH/assignments"
    # Only touch files that need it (fast even with thousands of photos)
    find "$DATA_PATH" \( ! -user "$PUID" -o ! -group "$PGID" \) -exec chown "$PUID:$PGID" {} + 2>/dev/null || true
    exec setpriv --reuid="$PUID" --regid="$PGID" --clear-groups "$0" "$@"
fi

umask "${UMASK:-002}"
cd /app

echo "[start] preparing the database..."
python -c "from run import app" || { echo "[start] could not prepare the database - see the error above"; exit 1; }

if [ "${RUN_SCHEDULER:-true}" = "true" ]; then
    (
        while true; do
            flask --app run:app reminder-scheduler --hour "${REMINDER_HOUR:-9}" || true
            echo "[start] reminder scheduler stopped - restarting in 30s"
            sleep 30
        done
    ) &
fi

#  gthread workers keep the site responsive while an AI request is running
#  --timeout 330   AI photo generation can take up to ~5 minutes
exec gunicorn --bind 0.0.0.0:8123 \
    --workers "${WEB_WORKERS:-2}" --worker-class gthread --threads 4 \
    --timeout 330 --graceful-timeout 30 \
    --access-logfile - run:app
