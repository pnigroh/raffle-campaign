#!/bin/bash
# Monthly restic repository integrity check. Read-only; safe with the
# no-delete key.
set -euo pipefail

# shellcheck disable=SC1091
source /srv/raffle/config/restic.env

LOG=/var/log/raffle/restic-check.log

{
    echo "===== $(date -Iseconds) check start ====="
    restic check --read-data-subset=5%
    echo "===== $(date -Iseconds) check end ====="
} >> "$LOG" 2>&1
