#!/bin/bash
# Two concurrent loops:
#   1. Event-driven: inotifywait on the watch dir, rclone copyto on every
#      close_write/moved_to. Sub-second latency for new uploads.
#   2. Periodic: every $SYNC_INTERVAL seconds, rclone sync the full tree
#      to catch anything inotify missed (kernel queue overflow, container
#      restart while files were arriving, large mv operations).
set -euo pipefail

: "${WATCH_DIR:?WATCH_DIR must be set}"
: "${REMOTE:?REMOTE must be set}"
: "${RCLONE_CONFIG:?RCLONE_CONFIG must be set}"
SYNC_INTERVAL="${SYNC_INTERVAL:-600}"

echo "[media-syncer] watch=$WATCH_DIR remote=$REMOTE sync_every=${SYNC_INTERVAL}s"
echo "[media-syncer] rclone version:"; rclone --version | head -n1

if [ ! -d "$WATCH_DIR" ]; then
    echo "[media-syncer] FATAL: $WATCH_DIR does not exist (is the bind mount wired?)"
    exit 1
fi
if [ ! -f "$RCLONE_CONFIG" ]; then
    echo "[media-syncer] FATAL: $RCLONE_CONFIG missing — drop rclone.conf into /srv/raffle/config/"
    exit 1
fi

# Initial reconciliation: ensure the remote matches the bind mount on boot.
echo "[media-syncer] initial reconciliation..."
rclone sync "$WATCH_DIR" "$REMOTE" --transfers 4 --checkers 8 --log-level INFO

# Periodic sync loop (background).
(
    while true; do
        sleep "$SYNC_INTERVAL"
        echo "[media-syncer] periodic sync starting..."
        rclone sync "$WATCH_DIR" "$REMOTE" --transfers 4 --checkers 8 --log-level INFO \
            || echo "[media-syncer] WARN: periodic sync exited non-zero"
    done
) &
PERIODIC_PID=$!

# inotify event loop (foreground).
echo "[media-syncer] starting inotify watcher..."
inotifywait -m -r -e close_write,moved_to --format '%w%f' "$WATCH_DIR" 2>/dev/null |
while IFS= read -r path; do
    rel="${path#$WATCH_DIR/}"
    echo "[media-syncer] event: $rel"
    rclone copyto "$path" "$REMOTE/$rel" --log-level INFO \
        || echo "[media-syncer] WARN: copy failed for $rel"
done

# inotifywait should never exit; if it does, kill the periodic loop and let
# the container restart policy bring us back.
kill "$PERIODIC_PID" 2>/dev/null || true
exit 1
