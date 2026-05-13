# Custom Postgres 16 image with pgBackRest binary installed.
# pgBackRest needs to live on the Postgres container because Postgres calls
# `archive_command = pgbackrest archive-push` directly during WAL rotation.
FROM postgres:16-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
        pgbackrest \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# pgBackRest expects /var/lib/pgbackrest (repo1) and /var/spool/pgbackrest
# to exist with the postgres user as owner. Inside the container both are
# bind-mounted from the host, but we create the mountpoints + perms here.
RUN install -d -o postgres -g postgres -m 700 /var/lib/pgbackrest \
    && install -d -o postgres -g postgres -m 700 /var/spool/pgbackrest \
    && install -d -o postgres -g postgres -m 750 /var/log/pgbackrest

# Postgres reads any *.conf in /etc/postgresql/conf.d after the main file.
# We ship a fragment that turns on archive_mode and points archive_command
# at pgbackrest. The fragment is mounted via compose into conf.d.
COPY postgresql.conf.fragment /etc/postgresql/conf.d/10-pgbackrest.conf
RUN chmod 644 /etc/postgresql/conf.d/10-pgbackrest.conf

# Init-time hook that creates a dedicated pgbackrest role with REPLICATION.
COPY init-pgbackrest-user.sh /docker-entrypoint-initdb.d/10-init-pgbackrest-user.sh
RUN chmod 755 /docker-entrypoint-initdb.d/10-init-pgbackrest-user.sh
