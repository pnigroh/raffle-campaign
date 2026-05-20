#!/bin/bash
# Nightly restic snapshot of /srv/raffle/media and /srv/raffle/pgbackrest
# to the encrypted, append-only B2 archive bucket.
#
# Credentials are sourced from /srv/raffle/config/restic.env (mode 600,
# root-owned). The B2 application key configured there has NO deleteFiles
# capability — this script can only ADD snapshots, never destroy old ones.
set -euo pipefail

# shellcheck disable=SC1091
source /srv/raffle/config/restic.env

LOG=/var/log/raffle/restic-backup.log
mkdir -p /var/log/raffle

{
    echo "===== $(date -Iseconds) backup start ====="
    restic backup \
        --tag nightly \
        --host raffle-prod \
        /srv/raffle/media \
        /srv/raffle/pgbackrest \
        /srv/raffle/themes
    echo "===== $(date -Iseconds) backup end ====="
} >> "$LOG" 2>&1
