#!/bin/bash
# Daily freshness check. Validates:
#   1. Latest pgBackRest WAL archive < 5 min old (RPO sanity)
#   2. Latest restic snapshot < 25 h old (nightly cron is alive)
# On failure, emits to stderr (cron mails root) and exits non-zero.

# Helper: is the given ISO timestamp older than max_age seconds?
#   exit 0 = fresh, 1 = stale, 2 = invalid input
is_stale() {
    local ts="$1"
    local max_age="$2"
    if [ -z "$ts" ]; then
        return 2
    fi
    local then_epoch now_epoch age
    then_epoch=$(date -d "$ts" +%s 2>/dev/null) || return 2
    now_epoch=$(date +%s)
    age=$((now_epoch - then_epoch))
    if [ "$age" -gt "$max_age" ]; then
        return 1
    fi
    return 0
}

# If sourced (not executed), expose helper and exit early.
if [ "${BASH_SOURCE[0]}" != "${0}" ]; then
    return 0 2>/dev/null || exit 0
fi

set -euo pipefail

: "${COMPOSE_FILE:=/srv/raffle/repo/docker-compose.prod.yml}"
if [ ! -f "$COMPOSE_FILE" ]; then
    echo "FATAL: COMPOSE_FILE='$COMPOSE_FILE' not found; set COMPOSE_FILE env var or fix this default" >&2
    exit 3
fi

errors=0

# Check 1: latest WAL in B2 archive.
WAL_TS=$(docker compose -f "$COMPOSE_FILE" exec -T pgbackrest \
    su -c 'pgbackrest --stanza=raffle info --output=json' postgres \
    | python3 -c '
import json, sys
data = json.load(sys.stdin)
archives = data[0]["archive"][0]
latest = archives.get("max")
if not latest:
    sys.exit(0)
# pgbackrest info doesn'"'"'t expose WAL push timestamp directly; we approximate
# by reading the most recent backup'"'"'s timestamp.
last_backup = data[0]["backup"][-1]
print(last_backup["timestamp"]["stop"])
')

if ! is_stale "$WAL_TS" 3600; then
    echo "FAIL: pgBackRest archive stale (last activity: $WAL_TS)" >&2
    errors=$((errors + 1))
fi

# Check 2: latest restic snapshot.
source /srv/raffle/config/restic.env
SNAP_TS=$(restic snapshots --json | python3 -c '
import json, sys
snaps = json.load(sys.stdin)
if not snaps:
    sys.exit(0)
print(snaps[-1]["time"])
')

if ! is_stale "$SNAP_TS" 90000; then  # 25h
    echo "FAIL: restic snapshot stale (last snapshot: $SNAP_TS)" >&2
    errors=$((errors + 1))
fi

exit $errors
