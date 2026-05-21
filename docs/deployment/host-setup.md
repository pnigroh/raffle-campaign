# Raffle Campaign — Host Setup Quick Reference

This page summarizes what lives where on the prod host. For full restore
procedures, see `restore-playbook.md`. For design rationale, see
`../superpowers/specs/2026-05-13-zero-data-loss-backup-design.md`.

## Filesystem layout

```
/srv/raffle/
├── pg/                  # Postgres PGDATA, owner 999:999, mode 700
├── media/               # MEDIA_ROOT (user uploads), bind-mounted into web + media-syncer
├── pgbackrest/          # pgBackRest local repo (repo1), owner 999:999
├── staticfiles/         # collected statics, rebuildable
├── migration/           # one-shot SQLite dump + the archived pre-migration db.sqlite3
└── config/              # all secret files, mode 600
    ├── pgbackrest.conf  # B2 repo2 credentials + cipher pass
    ├── rclone.conf      # B2 media bucket credentials
    └── restic.env       # B2 archive bucket credentials + restic passphrase
```

## Containers

| Container | Image | Restart policy | Purpose |
|---|---|---|---|
| raffle-prod | raffle-campaign-prod:latest | unless-stopped | Django + gunicorn |
| raffle-postgres | raffle-postgres:latest | unless-stopped | Postgres 16 + pgBackRest binary + cron-driven full/diff/incr backups |
| raffle-media-syncer | raffle-media-syncer:latest | unless-stopped | rclone + inotify event push |

## Host crons

| File | Schedule | Purpose |
|---|---|---|
| /etc/cron.d/raffle-restic | 0 3 * * * | Nightly restic snapshot |
| /etc/cron.d/raffle-restic | 0 5 1 * * | Monthly restic integrity check |
| /etc/cron.d/raffle-restic | 0 6 * * * | Daily backup-freshness check (mails on fail) |

## B2 buckets

| Bucket | Versioning | Key permissions |
|---|---|---|
| raffle-pgbackrest-XXXXXX | off | rw + delete (for pgbackrest retention) |
| raffle-media-XXXXXX | 90-day prior versions | rw, **no delete** |
| raffle-archive-XXXXXX | off | rw, **no delete** (restic on-host key); separate full-access key off-host for pruning |

## On-call commands

- Tail backup activity: `tail -f /var/log/raffle/restic-backup.log /var/log/pgbackrest/cron.log`
- Force a manual backup: `docker compose -f docker-compose.prod.yml exec -u postgres postgres pgbackrest --stanza=raffle --type=incr backup`
- Status of all backups: `docker compose -f docker-compose.prod.yml exec -u postgres postgres pgbackrest --stanza=raffle info`
- Manually run freshness check: `sudo /usr/local/bin/raffle-backup-freshness`

## Adding a new tenant domain

When onboarding a new client with their own branded domain:

1. **DNS** — point the hostname at the prod VPS.
2. **Reverse proxy** (Plesk) — add the new hostname to the existing app's vhost (or create a new vhost forwarding to the app container).
3. **ALLOWED_HOSTS** — add the new hostname to `ALLOWED_HOSTS` in `.env.prod`. Restart the web container.
4. **Domain row** — in Django admin → Domains → Add. Set hostname, display_name, and add the client user(s) to managers.
5. **Existing campaigns** — move any relevant campaigns to the new Domain via admin (Campaign change page → Domain dropdown).

After step 3 you can verify the configuration with:

```bash
docker exec raffle-prod python manage.py check
```

Any `campaigns.W001` warning means a Domain row references a hostname not in ALLOWED_HOSTS. Fix and restart.

**Note on visibility:** the W001 warning surfaces via `manage.py check` only — it is NOT printed at container startup. Operators must run `manage.py check` explicitly after editing Domain rows or `ALLOWED_HOSTS`.
