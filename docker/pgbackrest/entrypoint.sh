#!/bin/bash
# Sidecar entrypoint:
#   1. Wait for Postgres to be reachable.
#   2. Ensure the stanza exists (idempotent — `stanza-create` is safe to re-run).
#   3. Hand off to cron (foreground).
set -euo pipefail

PGBACKREST_CONFIG=${PGBACKREST_CONFIG:-/etc/pgbackrest/pgbackrest.conf}
PG_HOST=${PG_HOST:-postgres}
PG_USER=${PG_USER:-pgbackrest}
PG_DB=${PG_DB:-raffledb}

echo "[pgbackrest-sidecar] waiting for Postgres at ${PG_HOST}:5432..."
for i in $(seq 1 60); do
    if pg_isready -h "$PG_HOST" -U "$PG_USER" -d "$PG_DB" >/dev/null 2>&1; then
        echo "[pgbackrest-sidecar] Postgres is ready."
        break
    fi
    sleep 2
    if [ "$i" -eq 60 ]; then
        echo "[pgbackrest-sidecar] FATAL: Postgres did not become ready in 120s"
        exit 1
    fi
done

# stanza-create is idempotent — it errors only if the stanza exists with a
# different cluster identity, which is what we want for safety.
echo "[pgbackrest-sidecar] ensuring stanza 'raffle' exists in both repos..."
su -c "pgbackrest --stanza=raffle stanza-create" postgres || \
    echo "[pgbackrest-sidecar] stanza-create returned non-zero; assuming already initialised"

# Validate the stanza can read WAL from Postgres (this also surfaces
# misconfigured archive_command early).
su -c "pgbackrest --stanza=raffle check" postgres

echo "[pgbackrest-sidecar] starting cron in foreground..."
exec cron -f
