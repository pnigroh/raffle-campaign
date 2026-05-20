# Raffle Campaign — Restore Playbook

Last reviewed: 2026-05-13.

Four recovery scenarios are documented. Each is rehearsable; rehearsal results
are logged in `restore-rehearsal-log.md`.

## Inventory of secrets needed

All restore paths require, at minimum:

1. **B2 application keys** for `raffle-pgbackrest-*` and `raffle-media-*` buckets.
2. **pgBackRest cipher passphrase** (`repo2-cipher-pass` from `pgbackrest.conf`).
3. **Postgres password** (`POSTGRES_PASSWORD` from `.env.prod`).
4. **Django SECRET_KEY** (from `.env.prod`).
5. (For ransomware recovery only) **restic repository password** and **archive bucket B2 key**.

All five live in the operator password manager. Without them, **no restore is possible** — protect them accordingly.

## Scenario A: Full disaster recovery (host lost)

**When to use:** VPS terminated, disk unrecoverable, ransomware encrypted everything, etc.

1. Provision a fresh Linux host with Docker + docker compose.
2. `git clone <repo>`; `git checkout <prod branch>`.
3. Recreate the host filesystem layout:
   ```bash
   sudo install -d -o root -g root -m 755 /srv/raffle
   sudo install -d -o 999 -g 999 -m 700 /srv/raffle/pg
   sudo install -d -o 999 -g 999 -m 700 /srv/raffle/pgbackrest
   sudo install -d -o root -g root -m 755 /srv/raffle/media
   sudo install -d -o root -g root -m 755 /srv/raffle/staticfiles
   sudo install -d -o root -g root -m 700 /srv/raffle/config
   ```
4. Drop the three credential files into `/srv/raffle/config/` (pgbackrest.conf, rclone.conf, restic.env) — copies from your password manager.
5. Drop `.env.prod` next to `docker-compose.prod.yml`.
6. Build images: `docker compose -f docker-compose.prod.yml build`.
7. Start Postgres (Postgres will start empty):
   ```bash
   docker compose -f docker-compose.prod.yml up -d postgres
   ```
8. Wait for Postgres to be running, then **stop Postgres** (so we can restore into the empty PGDATA without conflict):
   ```bash
   docker compose -f docker-compose.prod.yml stop postgres
   ```
9. Restore from B2:
   ```bash
   docker compose -f docker-compose.prod.yml run --rm -u postgres postgres pgbackrest --stanza=raffle --repo=2 restore --delta
   ```
10. Start Postgres — it replays WAL to the latest archived segment:
    ```bash
    docker compose -f docker-compose.prod.yml start postgres
    docker compose -f docker-compose.prod.yml logs --tail=50 postgres
    ```
    Expect lines like `archive recovery complete` followed by `database system is ready`.
11. Restore media:
    ```bash
    docker compose -f docker-compose.prod.yml run --rm -v /srv/raffle/media:/data media-syncer \
        rclone sync b2:raffle-media-XXXXXX /data --transfers 4
    ```
12. Bring up the rest: `docker compose -f docker-compose.prod.yml up -d web media-syncer`.
13. Verify: log in, view a known submission, check row counts vs whatever snapshot you have.

**Expected RTO: 30 minutes.** **Expected RPO: ≤ 30 seconds of writes.**

## Scenario B: Point-in-time recovery (e.g. bad UPDATE)

**When to use:** application bug or operator mistake wrote bad data; you know the approximate timestamp before the bad write.

1. Stop the web container (no new writes during recovery):
   ```bash
   docker compose -f docker-compose.prod.yml stop web
   ```
2. Stop Postgres:
   ```bash
   docker compose -f docker-compose.prod.yml stop postgres
   ```
3. Restore to the target time:
   ```bash
   docker compose -f docker-compose.prod.yml run --rm -u postgres postgres pgbackrest --stanza=raffle --type=time --target='2026-05-13 14:23:00+00' restore --delta
   ```
4. Start Postgres → replays WAL up to the target time then pauses:
   ```bash
   docker compose -f docker-compose.prod.yml start postgres
   ```
5. Connect and verify data is at the target time. To resume normal operations:
   ```sql
   SELECT pg_wal_replay_resume();
   ```
6. Restart web: `docker compose -f docker-compose.prod.yml up -d web`.

**Caveat:** PITR rewrites history. All writes after the target time are gone. Communicate this with stakeholders.

## Scenario C: Single-file restore (accidental media delete)

**When to use:** a user-submitted photo was deleted from `/srv/raffle/media` (by app bug or operator).

The B2 bucket has 90-day versioning. Find the version:

```bash
docker compose -f docker-compose.prod.yml exec media-syncer \
    rclone lsf 'b2:raffle-media-XXXXXX/submissions/<filename>' --b2-versions
```

Restore the most recent prior version:

```bash
docker compose -f docker-compose.prod.yml run --rm \
    -v /srv/raffle/media:/data/media \
    --entrypoint rclone media-syncer \
    copyto 'b2:raffle-media-XXXXXX/submissions/<filename>-v<id>.jpg' \
           '/data/media/submissions/<filename>.jpg'
```

**Why `run --rm` instead of `exec`:** the running `media-syncer` container has `/data/media` mounted read-only by design (it's a sync source, not a target). The one-off `run --rm` invocation re-mounts it RW for the restore.

(The `inotify` watcher will see the restore as a new file and re-upload it as the current version. No further action needed.)

## Scenario D: Ransomware / archive-only recovery

**When to use:** the prod host's B2 application keys were compromised AND used to corrupt the live `raffle-pgbackrest` / `raffle-media` buckets. The archive bucket survives because (a) its B2 key has no delete permission, and (b) the restic passphrase is not on the host.

1. Provision a clean Linux host (do NOT reuse the compromised one).
2. Install restic.
3. From the password manager, populate `/srv/raffle/config/restic.env` with the **archive** bucket credentials and the restic passphrase.
4. List snapshots and pick one from before the compromise:
   ```bash
   source /srv/raffle/config/restic.env
   restic snapshots
   ```
5. Restore both bind-mount targets:
   ```bash
   restic restore <snapshot-id> --target / --include /srv/raffle/media --include /srv/raffle/pgbackrest
   ```
6. Restore Postgres from the pgBackRest **local** repo (which we just restored):
   - Reuse Scenario A steps 6-13, but pgBackRest can use `--repo=1` since the local repo is intact.

## Off-host maintenance: pruning the restic archive

The prod host's archive key has no delete permission. To prune old snapshots, run from a workstation or second machine with a separate, more-privileged key:

```bash
export RESTIC_REPOSITORY=b2:raffle-archive-XXXXXX:/raffle
export B2_ACCOUNT_ID=<ARCHIVE_FULL_ACCESS_KEY_ID>
export B2_ACCOUNT_KEY=<ARCHIVE_FULL_ACCESS_KEY>
export RESTIC_PASSWORD=<passphrase>
restic forget --keep-daily 14 --keep-weekly 8 --keep-monthly 24 --keep-yearly 10 --prune
```

Run this annually at most. Storage cost is low enough that pruning is optional for years.

## Themes during restore

`/srv/raffle/themes/` is backed up by restic alongside `/srv/raffle/media/`. After a restore:

1. Verify `/srv/raffle/themes/futboleros/` exists and contains the expected files.
2. If missing, run `docker exec raffle-prod python manage.py setup_default_theme --force` to repopulate from the in-repo source.
3. Verify any custom themes you've uploaded are present. If not, re-upload from your offline copy (themes other than the default are NOT in git).

## Quarterly rehearsal

Run Scenario A against a scratch host or VM. Log results in `restore-rehearsal-log.md`. If a rehearsal fails, treat it as a P0 — no backup work proceeds until restore is proven working again.
