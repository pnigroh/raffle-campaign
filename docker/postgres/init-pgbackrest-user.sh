#!/bin/bash
# Runs once on first DB init. Creates a role that pgbackrest uses to call
# pg_start_backup / pg_stop_backup. Using a dedicated role (not superuser)
# is the recommended pattern.
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE ROLE pgbackrest WITH LOGIN REPLICATION;
    GRANT EXECUTE ON FUNCTION pg_backup_start(text, boolean) TO pgbackrest;
    GRANT EXECUTE ON FUNCTION pg_backup_stop(boolean) TO pgbackrest;
    GRANT EXECUTE ON FUNCTION pg_create_restore_point(text) TO pgbackrest;
    GRANT EXECUTE ON FUNCTION pg_switch_wal() TO pgbackrest;
EOSQL
