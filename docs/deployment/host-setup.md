# Raffle Campaign — Host Setup Quick Reference

This page summarizes what lives where on the prod host. For full restore
procedures, see `restore-playbook.md`. For design rationale, see
`../superpowers/specs/2026-05-13-zero-data-loss-backup-design.md`.

## Filesystem layout

```
/srv/raffle/
├── pg/                  # Postgres PGDATA, owner 999:999, mode 700
├── media/               # MEDIA_ROOT (user uploads), bind-mounted into web + media-syncer
├── themes/              # Theme bundles (extracted .zip archives)
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

## Theme asset routing (nginx)

Theme bundles ship images, fonts, and CSS under `/srv/raffle/themes/<slug>/assets/`. Add this `location` block to the app's nginx vhost (above the Django proxy_pass block):

```nginx
location ~ ^/theme-assets/([^/]+)/(.+)$ {
    alias /srv/raffle/themes/$1/assets/$2;
    expires 7d;
    add_header Cache-Control "public, immutable";
}
```

This bypasses Django for asset requests; the app only sees `/submit/<slug>/` and `/dashboard/`.

If you skip this step, theme assets will still serve in dev (Django handles the route), but prod is slower because every asset goes through gunicorn.
