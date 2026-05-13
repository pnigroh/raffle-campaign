# Zero-Data-Loss Cutover — Live State

> **What this is:** a single-page operator log that tracks the in-flight cutover from SQLite to the new Postgres + B2 backup stack. Updated as we go. Will be deleted (or archived under `docs/deployment/history/`) once the cutover is fully complete and the first restore rehearsal is logged.

**Status:** Paused — waiting on Backblaze B2 registration to come back online.
**Last updated:** 2026-05-13
**Branch:** `zero-data-loss-backup` (PR #1: https://github.com/pnigroh/raffle-campaign/pull/1)
**Authoritative plan:** [`docs/superpowers/plans/2026-05-13-zero-data-loss-backup.md`](../superpowers/plans/2026-05-13-zero-data-loss-backup.md)
**Authoritative spec:** [`docs/superpowers/specs/2026-05-13-zero-data-loss-backup-design.md`](../superpowers/specs/2026-05-13-zero-data-loss-backup-design.md)

---

## Quick resume

If you only have 60 seconds, read these three things:

1. **Next concrete step:** Backblaze B2 registration / sign-in at https://secure.backblaze.com → continue from "Phase B: B2 setup" below.
2. **Nothing on prod has been touched yet.** The local dev tree has 19 commits on `zero-data-loss-backup`; PR #1 is open. Prod is still running the legacy SQLite single-service compose.
3. **The architecture changed during dev** — the original 4-service design had a `pgbackrest` sidecar, but smoke testing proved it can't reach Postgres-in-another-container. The branch now uses 3 services: `postgres` (with cron + pgBackRest inside), `web`, `media-syncer`. The spec, plan, and playbook were all updated to match.

---

## What's done

### Code (PR #1 — branch `zero-data-loss-backup`)

| Plan task | Status | Commit(s) |
|---|---|---|
| 1. Backup commit + branch | ✅ | `80dd39d` |
| 2. DATABASE_URL env-driven | ✅ | `6ebb4cb`, `5e14eb3` |
| 3. Postgres image with pgBackRest | ✅ | `214b6d9`, `bcf16b6` (smoke-test fixes), `31a9de5` (cron added) |
| 4. ~~pgBackRest sidecar image~~ | **OBSOLETED** by smoke-test refactor | (was `1b0b71a`, removed in `31a9de5`) |
| 5. media-syncer image | ✅ | `4934d9c` |
| 6. compose + Dockerfile.prod | ✅ | `3742e20`, `511504d` (wait-loop fix), `31a9de5` (sidecar dropped) |
| 7. sequence-reset helper + test | ✅ | `7fca4ac` |
| 8. SQLite→Postgres migration script | ✅ | `97bbacb`, `ce97bc9` (precount.txt fix) |
| 9. Local end-to-end smoke test | ✅ | (verification only; bugs fixed via `bcf16b6` + `31a9de5`) |
| 10. **B2 console setup** | **PAUSED** | — |
| 11. /srv/raffle/... on prod | — | — |
| 12. Credential files on prod | — | — |
| 13. First Postgres boot on prod | — | — |
| 14. SQLite→Postgres cutover | — | — |
| 15. Bring up media-syncer on prod | — | — |
| 16. Restic scripts + cron | partial — scripts written, host install pending | `311b797`, `e32c3cb` |
| 17. Restic init + first snapshot | — | — |
| 18. Backup-freshness monitor | partial — script written, host install pending | `311b797`, `e32c3cb` |
| 19. Restore playbook + rehearsal log | ✅ | `7bd5992`, `e0f8593` |
| 20. First restore rehearsal | — | — |
| 21. Decommission prod-data/ | ✅ | `7271dec` |
| 22. Open PR for dev-side changes | ✅ | PR #1 |

### Local smoke test results (Task 9)

Ran 2026-05-13 under `~/raffle-smoke/` with a local rclone backend as fake B2. All paths green:

- Postgres + pgBackRest + cron daemon running inside one container (cron PID 8 alongside `postgres`)
- `archive_mode=on` + WAL `archive-push` functional
- `pgbackrest stanza-create` + full + incremental backup completed (30.5 MB DB → 4 MB compressed; full in 28 s, incr in 1.9 s)
- Media-syncer inotify push for flat files and `submissions/<uuid>.jpg` subpaths
- Django web: wait-loop → migrate → collectstatic → gunicorn → `GET /dashboard/login/` returns HTTP 200

### Bugs caught and fixed during smoke testing

1. **`pg_read_all_settings` grant missing on the `pgbackrest` role** → `pgbackrest stanza-create` failed. Fix in `bcf16b6`: `docker/postgres/init-pgbackrest-user.sh` now grants it.
2. **`/etc/postgresql/conf.d/10-pgbackrest.conf` fragment never loaded** → `archive_mode` stayed off, no WAL ever pushed. The stock `postgres:16-bookworm` `postgresql.conf` has no `include_dir`. Fix in `bcf16b6`: the init script now appends the fragment to `$PGDATA/postgresql.conf` at first init so it takes effect on the post-init server restart.
3. **pgBackRest sidecar couldn't reach Postgres** → sidecar crash-looped. pgBackRest's connection model is local-socket OR SSH OR TLS, and we configured none. Fix in `31a9de5`: dropped the sidecar entirely; cron + `/etc/cron.d/pgbackrest` now live inside the Postgres image (where pgBackRest is already installed and uses the local socket). Stack drops from 4 services to 3.

### Other fixes (from the pre-merge code review)

| Issue | Fix commit |
|---|---|
| Restore-playbook Scenario C wrote through a `:ro` mount | `e0f8593` (use `docker run --rm` with RW mount) |
| Migration script referenced `precount.txt` but never created it | `ce97bc9` (added Phase 0/7 row-count baseline) |
| Freshness script shipped with hardcoded `/path/to/...` placeholder | `e32c3cb` (parameterized via `COMPOSE_FILE` env var with fail-fast guard) |
| `.env.example` missing prod-only `POSTGRES_*` vars | `ae1349b` (added commented hints) |

---

## Operator gotcha: snap-installed Docker

This was caught on the dev box during smoke testing. If your Docker daemon is installed via snap (`/var/snap/docker/common/var-lib-docker`), **snap confinement prevents the daemon from reading files outside `$HOME`**. Symptom: file bind mounts under `/tmp/...` or `/srv/...` get silently turned into empty *directories* inside the container, surfacing as errors like:

```
P00  ERROR: [042]: unable to read '/etc/pgbackrest/pgbackrest.conf': [21] Is a directory
```

**To confirm whether you're affected:** `docker info | grep "Docker Root"`. If the path contains `/snap/`, you are.

**Two options:**
- Move all bind mounts to `$HOME` (fine for dev / smoke testing — that's what we did).
- For prod: install Docker via apt (`docker-ce` package) instead of snap. Plesk-managed VPSes typically already have apt Docker, so this likely doesn't bite on the production target. But **verify before running Task 11** by checking `docker info` output on the prod host.

---

## How to resume — step by step

### Phase A: confirm prerequisites still hold

```bash
# On dev machine:
cd /home/elgran/Projects/raffle-campaign
git fetch origin
git checkout zero-data-loss-backup
git pull
git log main..HEAD --oneline | head    # confirm 19 commits ahead of main
.venv/bin/python -m pytest              # confirm 122 tests still pass
```

If any test fails or commits look unexpected, stop and investigate before continuing.

### Phase B: B2 setup (Task 10)

Once https://secure.backblaze.com is back online:

1. **Sign in / register.** Free tier is fine; storage cost for our data sizes is pennies/month.

2. **Pick a globally-unique 6-character suffix** (e.g., your initials + 4 random digits — `pn4f9k`). Use it for all three buckets.

3. **Create the three buckets.** Buckets → Create a Bucket. Repeat for each:

   | Bucket name | Files in Bucket | Default Encryption | Object Lock |
   |---|---|---|---|
   | `raffle-pgbackrest-<suffix>` | Private | Enable (SSE-B2) | Disable |
   | `raffle-media-<suffix>` | Private | Enable (SSE-B2) | Disable |
   | `raffle-archive-<suffix>` | Private | Enable (SSE-B2) | Disable |

4. **Enable 90-day version retention on the media bucket only.** Click `raffle-media-<suffix>` → Lifecycle Settings → "Use a custom lifecycle rule" → set "Keep prior versions of files for this many days: **90**" → Save.

5. **Create three application keys** (App Keys → Add a New Application Key). Each key is scoped to a single bucket. **Capabilities are critical for the anti-ransomware property — get them right:**

   | Key name | Bucket | Capabilities | NOT included |
   |---|---|---|---|
   | `raffle-pgbackrest-rw` | `raffle-pgbackrest-<suffix>` | listBuckets, listFiles, readFiles, **writeFiles, deleteFiles** | — |
   | `raffle-media-rw-nodelete` | `raffle-media-<suffix>` | listBuckets, listFiles, readFiles, **writeFiles** | **deleteFiles** |
   | `raffle-archive-append-only` | `raffle-archive-<suffix>` | listBuckets, listFiles, readFiles, **writeFiles** | **deleteFiles** |

   For each key, B2 displays the `keyID` and `applicationKey` **exactly once**. Save them to your password manager *immediately*. The `applicationKey` value cannot be recovered later — if you lose it, you delete the key and make a new one.

6. **Generate two more secrets in your password manager** (independent of B2):
   - **`repo2-cipher-pass`** — `openssl rand -hex 32` — pgBackRest uses this to encrypt B2-side backups so even if a B2 admin or attacker reads the bucket they can't read the data.
   - **Restic repository password** — `openssl rand -hex 32` — restic uses this to encrypt the archive bucket. **This passphrase is NOT stored on the prod host** — only in your password manager. Without it, archive restore is impossible.

7. **Record the bucket suffix and write down the 5 stored items in your password manager:**

   - `raffle / B2 / pgbackrest` — keyID, applicationKey, bucket name, endpoint (`s3.us-west-002.backblazeb2.com` is the typical default, but B2 console shows the right one), `repo2-cipher-pass`
   - `raffle / B2 / media` — keyID, applicationKey, bucket name
   - `raffle / B2 / archive` — keyID, applicationKey, bucket name, **restic passphrase** (separate from B2 keys; pasted into `restic.env` on the host)

These six entries are the **only secrets needed to restore from scratch**. Treat them accordingly.

### Phase C: decide on the merge timing

Two reasonable patterns:

- **Merge PR #1 first** (cleaner deploy story — prod always pulls main). Squash- or merge-commit; then on prod `git checkout main && git pull`. The risk is that if a bug surfaces in Phase D-F, you've already merged.
- **Keep PR open; pull the branch directly on prod.** On prod: `git fetch && git checkout zero-data-loss-backup`. Merge only after cutover succeeds. Lower risk; messier git story.

Either works. Pick one and stick with it for the cutover. Recommendation: **merge first** if you have a way to roll back (the SQLite db.sqlite3 backup commit `80dd39d` means rolling back the code is one `git revert` away; prod state is more nuanced).

### Phase D: prod host filesystem (Task 11)

SSH to the Plesk VPS, then:

```bash
# Verify Docker is NOT snap-installed (see "Operator gotcha" above):
docker info | grep "Docker Root"
# Expected: /var/lib/docker  (or similar — NOT containing /snap/)

# Create the filesystem tree:
sudo install -d -o root  -g root  -m 755 /srv/raffle
sudo install -d -o 999   -g 999   -m 700 /srv/raffle/pg            # postgres uid:gid in container
sudo install -d -o 999   -g 999   -m 700 /srv/raffle/pgbackrest    # same uid; pgbackrest writes here
sudo install -d -o root  -g root  -m 755 /srv/raffle/media
sudo install -d -o root  -g root  -m 755 /srv/raffle/staticfiles
sudo install -d -o root  -g root  -m 700 /srv/raffle/config
sudo install -d -o root  -g root  -m 700 /srv/raffle/migration

ls -la /srv/raffle/
# Expected: pg and pgbackrest show owner 999:999; config and migration are root:root mode 700.
```

### Phase E: prod credentials (Task 12)

Still on the prod host, paste the credentials from your password manager into three files. **Substitute every `XXXXXX`, `YOUR_*`, and `GENERATE_*` placeholder with the real values.**

```bash
# 1) pgbackrest.conf
sudo tee /srv/raffle/config/pgbackrest.conf > /dev/null <<'EOF'
[global]
repo1-path=/var/lib/pgbackrest
repo1-retention-full=4
repo1-retention-diff=14

repo2-type=s3
repo2-s3-bucket=raffle-pgbackrest-XXXXXX
repo2-s3-endpoint=s3.us-west-002.backblazeb2.com
repo2-s3-region=us-west-002
repo2-s3-key=YOUR_B2_KEY_ID
repo2-s3-key-secret=YOUR_B2_APPLICATION_KEY
repo2-path=/raffle
repo2-retention-full=12
repo2-retention-diff=90
repo2-cipher-type=aes-256-cbc
repo2-cipher-pass=GENERATE_A_LONG_RANDOM_STRING

archive-async=y
spool-path=/var/spool/pgbackrest
log-level-console=info
log-level-file=detail
process-max=4

[raffle]
pg1-path=/var/lib/postgresql/data
pg1-port=5432
pg1-user=pgbackrest
pg1-database=raffledb
EOF
sudo chmod 600 /srv/raffle/config/pgbackrest.conf
sudo chown 999:999 /srv/raffle/config/pgbackrest.conf

# 2) rclone.conf (media bucket key — no delete)
sudo tee /srv/raffle/config/rclone.conf > /dev/null <<'EOF'
[b2]
type = b2
account = YOUR_B2_MEDIA_KEY_ID
key = YOUR_B2_MEDIA_APPLICATION_KEY
EOF
sudo chmod 600 /srv/raffle/config/rclone.conf

# 3) restic.env (archive bucket key — no delete; offline passphrase)
sudo tee /srv/raffle/config/restic.env > /dev/null <<'EOF'
export RESTIC_REPOSITORY="b2:raffle-archive-XXXXXX:/raffle"
export B2_ACCOUNT_ID="YOUR_ARCHIVE_KEY_ID"
export B2_ACCOUNT_KEY="YOUR_ARCHIVE_APPLICATION_KEY"
export RESTIC_PASSWORD="YOUR_LONG_RESTIC_PASSWORD"
EOF
sudo chmod 600 /srv/raffle/config/restic.env

# 4) .env.prod (next to docker-compose.prod.yml in the repo checkout)
cd /path/to/raffle-campaign-checkout
sudo tee .env.prod > /dev/null <<EOF
SECRET_KEY=$(openssl rand -hex 32)
DEBUG=False
ALLOWED_HOSTS=raffle.yourdomain.example,localhost,127.0.0.1
CSRF_TRUSTED_ORIGINS=https://raffle.yourdomain.example
POSTGRES_DB=raffledb
POSTGRES_USER=raffleuser
POSTGRES_PASSWORD=$(openssl rand -hex 24)
DATABASE_URL=postgres://raffleuser:PASTE_THE_ABOVE_POSTGRES_PASSWORD_HERE@postgres:5432/raffledb
EOF
sudo chmod 600 .env.prod
```

**Important manual edit:** the `.env.prod` heredoc evaluates each `$(openssl rand ...)` independently — so the password set in `POSTGRES_PASSWORD` and the one embedded in `DATABASE_URL` will *not* match. Open `.env.prod` and copy the `POSTGRES_PASSWORD` value into the `DATABASE_URL`'s password slot. Save the final `SECRET_KEY`, `POSTGRES_PASSWORD`, and `repo2-cipher-pass` to your password manager under `raffle / prod / .env.prod`.

### Phase F: first Postgres boot on prod (Task 13)

```bash
cd /path/to/raffle-campaign-checkout
git checkout main          # if you merged PR #1
# or: git checkout zero-data-loss-backup  if you kept it open

# Stop the legacy SQLite-backed stack (if running)
docker compose -f docker-compose.prod.yml down

# Build the two new images
docker compose --env-file .env.prod -f docker-compose.prod.yml build

# Start just postgres (NOT web yet) — we want to verify backups before live traffic
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d postgres

# Wait for healthy + verify init
docker compose --env-file .env.prod -f docker-compose.prod.yml ps
docker compose --env-file .env.prod -f docker-compose.prod.yml logs --tail=80 postgres | grep -E "(ready|pgbackrest)"
# Expected: "database system is ready" + "CREATE ROLE" + "GRANT" lines from the init script

# Force a WAL push and verify both repos accept it
docker compose --env-file .env.prod -f docker-compose.prod.yml exec postgres \
    psql -U raffleuser -d raffledb -c "SELECT pg_switch_wal();"
sleep 30   # let archive-async flush

# Local repo:
docker compose --env-file .env.prod -f docker-compose.prod.yml exec -u postgres postgres \
    ls /var/lib/pgbackrest/archive/raffle/16-1/

# Both repos (B2 should also have the WAL by now):
docker compose --env-file .env.prod -f docker-compose.prod.yml exec -u postgres postgres \
    pgbackrest --stanza=raffle stanza-create
docker compose --env-file .env.prod -f docker-compose.prod.yml exec -u postgres postgres \
    pgbackrest --stanza=raffle check
docker compose --env-file .env.prod -f docker-compose.prod.yml exec -u postgres postgres \
    pgbackrest --stanza=raffle info
# Expected: "completed successfully" + repo1 AND repo2 both listed
```

If `check` fails for repo2, the most likely cause is B2 credentials. Re-verify `repo2-s3-key`, `repo2-s3-key-secret`, `repo2-s3-bucket`, and `repo2-s3-endpoint` in `pgbackrest.conf`.

### Phase G: SQLite → Postgres migration (Task 14)

**Maintenance window** — Django will be down for 5-10 minutes. Announce it before starting.

```bash
# Sanity-check legacy DB still works (briefly):
docker compose -f docker-compose.prod.yml exec web python manage.py check

# Then run the migration script:
./scripts/migrate_sqlite_to_postgres.sh 2>&1 | tee /srv/raffle/migration/migration.log
```

The script does 7 phases (capture row counts → dumpdata → stop web → bring up postgres → migrate → loaddata + sequence reset → start web). At the end it prints fresh row counts; compare against `/srv/raffle/migration/precount.txt`. Any diff → DO NOT archive `db.sqlite3` yet — investigate first.

If row counts match, smoke test the site:
- Log into `/dashboard/login/` with an existing user
- View a campaign detail page
- Submit a test entry through the public form
- Trigger a small raffle draw

If anything fails, you can roll back: revert `.env.prod`'s `DATABASE_URL` to `sqlite:///db.sqlite3`, restore the legacy SQLite file, `docker compose up -d web`. The Postgres data stays on `/srv/raffle/pg` untouched for a retry.

When you're satisfied, take a fresh full pgbackrest backup so the rest of the cutover has a clean baseline:

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml exec -u postgres postgres \
    pgbackrest --stanza=raffle --type=full backup
```

### Phase H: media-syncer on prod (Task 15)

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d media-syncer
docker compose --env-file .env.prod -f docker-compose.prod.yml logs --tail=50 media-syncer
# Expected: "initial reconciliation..." → completes → "starting inotify watcher..."

# Verify B2 has the existing media:
docker compose --env-file .env.prod -f docker-compose.prod.yml exec media-syncer \
    rclone size b2:raffle-media-XXXXXX
# Compare against:  du -sb /srv/raffle/media
```

Submit a real photo entry through the public form, then within seconds:

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml exec media-syncer \
    rclone lsf b2:raffle-media-XXXXXX/submissions/ | tail
# Expected: the just-uploaded filename appears.
```

### Phase I: restic + freshness cron on host (Tasks 16-18)

```bash
# Install restic (apt is fine if it's >= 0.16; otherwise grab the binary from GitHub releases)
sudo apt-get update && sudo apt-get install -y restic
restic version

# Install the scripts already in the repo to /usr/local/bin/
sudo install -m 755 scripts/raffle-restic-backup.sh    /usr/local/bin/raffle-restic-backup
sudo install -m 755 scripts/raffle-restic-check.sh     /usr/local/bin/raffle-restic-check
sudo install -m 755 scripts/raffle-backup-freshness.sh /usr/local/bin/raffle-backup-freshness

# Point the freshness check at the actual compose file location (or set COMPOSE_FILE in cron):
sudo sed -i 's|/srv/raffle/repo/docker-compose.prod.yml|'"$(pwd)"'/docker-compose.prod.yml|' \
    /usr/local/bin/raffle-backup-freshness
# (or leave the default and put the repo at /srv/raffle/repo/)

# Initialize the restic repo (one-shot)
source /srv/raffle/config/restic.env
restic init
# Expected: "created restic repository <hash> at b2:raffle-archive-XXXXXX:/raffle"

# Run the first manual snapshot to validate
sudo /usr/local/bin/raffle-restic-backup
tail -40 /var/log/raffle/restic-backup.log
# Expected: "Added to the repository: <size>"

source /srv/raffle/config/restic.env && restic snapshots
# Expected: 1 snapshot tagged 'nightly', host 'raffle-prod'

# Install cron entries
sudo tee /etc/cron.d/raffle-restic > /dev/null <<'EOF'
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
MAILTO=root

0 3 * * * root /usr/local/bin/raffle-restic-backup
0 5 1 * * root /usr/local/bin/raffle-restic-check
0 6 * * * root /usr/local/bin/raffle-backup-freshness
EOF
sudo chmod 644 /etc/cron.d/raffle-restic
sudo systemctl reload cron   # or: sudo service cron reload

# Verify root mail goes somewhere you actually read:
sudo grep '^root:' /etc/aliases   # or set it via /etc/aliases + `sudo newaliases`

# Run the freshness check once manually
sudo /usr/local/bin/raffle-backup-freshness && echo "OK"
```

### Phase J: first restore rehearsal (Task 20)

Use `docs/deployment/restore-playbook.md` Scenario A. Either:
- Spin up a scratch VM and run the full restore from B2, end to end, timing it.
- Or `docker compose run --rm -u postgres postgres pgbackrest --stanza=raffle --dry-run --repo=2 restore` to a scratch path on the same host for a quick sanity check.

Append the result to `docs/deployment/restore-rehearsal-log.md` (one row per rehearsal).

If the rehearsal succeeds, the cutover is **done**. Update memory + delete this file (or move it to `docs/deployment/history/2026-XX-cutover-complete.md` if you want to keep the record).

---

## Files / locations cheat sheet

### On the dev tree (already in git)

| Path | Purpose |
|---|---|
| `docker/postgres/Dockerfile` | Postgres 16 + pgBackRest + cron |
| `docker/postgres/init-pgbackrest-user.sh` | Creates pgbackrest role + appends conf to PGDATA |
| `docker/postgres/postgresql.conf.fragment` | archive_mode + archive_command settings |
| `docker/postgres/postgres-entrypoint.sh` | Starts cron daemon, then exec docker-entrypoint |
| `docker/postgres/pgbackrest-crontab` | Hourly incr / daily diff / weekly full schedule |
| `docker/media-syncer/Dockerfile` | alpine + rclone + inotify-tools |
| `docker/media-syncer/entrypoint.sh` | inotify event loop + 10-min reconciliation |
| `docker-compose.prod.yml` | 3-service stack (postgres, web, media-syncer) |
| `Dockerfile.prod` | Django web image; CMD has Postgres wait-loop |
| `scripts/migrate_sqlite_to_postgres.sh` | One-shot SQLite → Postgres orchestrator |
| `scripts/reset_postgres_sequences.py` | Post-loaddata SETVAL helper (with unit tests) |
| `scripts/raffle-restic-backup.sh` | Host-installed nightly restic backup |
| `scripts/raffle-restic-check.sh` | Host-installed monthly integrity check |
| `scripts/raffle-backup-freshness.sh` | Host-installed daily freshness alert |
| `docs/deployment/restore-playbook.md` | Operator runbook (4 scenarios) |
| `docs/deployment/host-setup.md` | Quick reference for filesystem + containers + crons |
| `docs/deployment/restore-rehearsal-log.md` | Append-only rehearsal log |

### On the prod host (after Phase D-E)

| Path | Contents | Mode |
|---|---|---|
| `/srv/raffle/pg/` | Postgres PGDATA | 700, owner 999:999 |
| `/srv/raffle/pgbackrest/` | pgBackRest local repo (repo1) | 700, owner 999:999 |
| `/srv/raffle/media/` | User uploads | 755, owner root |
| `/srv/raffle/staticfiles/` | Collected statics | 755, owner root |
| `/srv/raffle/migration/` | One-shot migration artifacts | 700, owner root |
| `/srv/raffle/config/pgbackrest.conf` | B2 repo2 credentials + cipher pass | 600, owner 999:999 |
| `/srv/raffle/config/rclone.conf` | B2 media-bucket credentials | 600 |
| `/srv/raffle/config/restic.env` | B2 archive-bucket credentials + restic passphrase | 600 |
| `<repo>/.env.prod` | Django SECRET_KEY + Postgres + DATABASE_URL | 600 |
| `/usr/local/bin/raffle-restic-backup` | nightly cron target | 755 |
| `/usr/local/bin/raffle-restic-check` | monthly integrity check | 755 |
| `/usr/local/bin/raffle-backup-freshness` | daily alerting | 755 |
| `/etc/cron.d/raffle-restic` | cron schedule for the three above | 644 |
| `/var/log/raffle/` | restic logs | dir created by scripts |
| `/var/log/pgbackrest/` | pgBackRest cron logs | dir created at first run |

### Secrets to keep in the password manager

These 6 entries are the **only secrets needed to restore from scratch**. If you lose them all, the backup is unreadable.

1. `raffle / B2 / pgbackrest` — keyID, applicationKey, bucket name, endpoint, **`repo2-cipher-pass`**
2. `raffle / B2 / media` — keyID, applicationKey, bucket name
3. `raffle / B2 / archive` — keyID, applicationKey, bucket name, **restic passphrase**
4. `raffle / prod / .env.prod` — Django `SECRET_KEY`, `POSTGRES_PASSWORD`
5. (Optional, future) `raffle / B2 / archive-full-access` — separate B2 key with delete capability, for off-host restic pruning. Held on a workstation, NOT on prod.

---

## Architecture notes worth re-reading before continuing

### Why the sidecar was dropped

The original spec had a 4th service: a separate `pgbackrest` sidecar container running the cron schedule. Smoke testing revealed pgBackRest's connection model is **either local Unix socket OR remote via SSH/TLS server**. Containers don't share Unix sockets, and we hadn't configured SSH or TLS. The sidecar crash-looped on its startup `pgbackrest check` call.

Three potential fixes were considered:
- Set up pgBackRest TLS server mode (self-signed certs both sides) — ~30 min of work + cert rotation later
- Mount the Docker socket into the sidecar so it could `docker exec` into postgres — privilege escalation risk
- **Move cron into the postgres container** ✅ chosen

The postgres image already has pgBackRest installed (it has to, because Postgres calls `archive_command = pgbackrest archive-push %p`). Adding `cron` + a system crontab is one extra package and ~10 lines of entrypoint wrapper. The local Unix socket Just Works. **Topology is simpler (3 containers instead of 4); operationally identical for our scale.**

### Why two pgBackRest repos

`repo1` is local (`/srv/raffle/pgbackrest`) — fast restore on the same host (~30 s RTO for a small DB). `repo2` is B2 — survives total host loss (~30 min RTO). pgBackRest pushes WAL and full/diff/incr backups to **both** repos. The cron schedule and `archive-async=y` mean Postgres never blocks on the B2 push.

### Why three B2 buckets with different key permissions

- `raffle-pgbackrest-*` (key has delete) — pgBackRest manages its own retention via `repo2-retention-full` / `repo2-retention-diff`; needs delete to expire old fulls.
- `raffle-media-*` (key has **no** delete) — media is append-mostly; 90-day version retention via bucket lifecycle gives us undelete. If the prod host is compromised, the attacker cannot purge older versions from this bucket.
- `raffle-archive-*` (key has **no** delete, **separate** passphrase held offline) — restic encrypted snapshots. Even if every other credential leaks, this bucket is encrypted with a passphrase that **does not live on the prod host**, so a host compromise cannot read or destroy it.

Pruning the archive bucket is an off-host operation using a more-privileged B2 key kept on a workstation, run annually at most.

### Why `archive-async=y`

`archive_command` runs synchronously inside Postgres's `bgwriter` process. If pgBackRest's push to B2 is slow (e.g., network blip), `archive_command` would block, WAL would queue, and worst case Postgres would refuse new writes. `archive-async=y` makes pgBackRest spool WAL segments locally and push them asynchronously — Postgres returns from `archive-push` in milliseconds regardless of B2's response time.

---

## How to handle resumption from a new Claude session

If you start a new Claude conversation later and want to pick this up:

1. Open the conversation in the `raffle-campaign` working directory.
2. Say something like *"Resume the zero-data-loss cutover — read `docs/deployment/cutover-state.md` and tell me where we left off."*
3. Claude will read this file + the project memory (`project_zero_data_loss_backup.md`) and have full context.

The memory pointer (`MEMORY.md` → `project_zero_data_loss_backup.md`) is automatically loaded at session start, so Claude already knows roughly where things stand. This document is the detailed source of truth.
