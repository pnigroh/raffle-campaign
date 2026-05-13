FROM debian:bookworm-slim

# Add PGDG apt repository so we get the same pgBackRest version as the
# postgres:16-bookworm base image (Debian bookworm ships an older 2.45).
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        gnupg \
    && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
        | gpg --dearmor -o /etc/apt/trusted.gpg.d/pgdg.gpg \
    && echo "deb https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" \
        > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update && apt-get install -y --no-install-recommends \
        pgbackrest \
        cron \
        postgresql-client-16 \
        tini \
    && rm -rf /var/lib/apt/lists/*

# Match the Postgres container's expectations.
# pgbackrest's apt package already creates a postgres user/group; we just
# ensure the uid/gid are pinned to 999 and the home directory exists.
RUN groupmod -g 999 postgres \
    && usermod -u 999 -g 999 -m -d /home/postgres -s /bin/bash postgres \
    && install -d -o postgres -g postgres -m 700 /var/lib/pgbackrest \
    && install -d -o postgres -g postgres -m 700 /var/spool/pgbackrest \
    && install -d -o postgres -g postgres -m 750 /var/log/pgbackrest

COPY crontab /etc/cron.d/pgbackrest
RUN chmod 644 /etc/cron.d/pgbackrest \
    && crontab -u postgres /etc/cron.d/pgbackrest

COPY entrypoint.sh /entrypoint.sh
RUN chmod 755 /entrypoint.sh

USER root
ENTRYPOINT ["/usr/bin/tini", "--", "/entrypoint.sh"]
