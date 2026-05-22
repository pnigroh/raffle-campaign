# Plesk Deployment Runbook — Raffle Campaign (Promo-Domo)

> ⚠️ **Superseded by `docs/deployment/cutover-state.md` (2026-05-19).**
> This runbook describes the legacy SQLite single-service stack. The production stack moved to Postgres + pgBackRest + media-syncer + restic when PR #1 merged. PRs #2 (multi-domain) and #3 (themes) layered on top of that. **For new deploys, follow `cutover-state.md` instead** — it covers Postgres bring-up, Domain bootstrap, and the `/theme-assets/` nginx block.
> Kept here as a reference for the pre-cutover topology. Some Phase 1 task descriptions (Dockerfile.prod, settings.py proxy-aware block) remain accurate background reading.

**Target stack:** Plesk server (any OS where the Docker extension is available — Ubuntu 22.04, Debian 12, AlmaLinux 8/9, CentOS 7, RHEL — Plesk Obsidian 18.x).
**Application:** Django 4.2 + SQLite, served by gunicorn inside Docker, fronted by Plesk Nginx.
**Initial data:** the current dev SQLite (Futboleros campaign, 8 submissions, 2 raffles + audit logs, prize, manager test user, Campaign Managers group) + ~1.5 MB of media uploads + ~10 MB of static assets.

> Replace these placeholders before running anything:
> - `DOMAIN.example.com` → your real domain (e.g. `promo-domo.example.com`)
> - `203.0.113.42` → your Plesk server's public IP
> - `STRONGADMIN_PW` → the password you want for the production superuser
> - `PROD_SECRET_KEY` → a freshly-generated 50-character random string (see Phase 1, step 5)

---

## Phase 0 — Decisions & prerequisites

| Decision | Choice for this plan |
|---|---|
| Database | SQLite (single file, easy to back up via `cp` + `tar`) |
| Initial data | Load the current dev DB + media on first deploy |
| Domain | Real domain pointed at the Plesk server (HTTPS via Plesk Let's Encrypt) |
| Container | Docker Compose, fronted by Plesk Nginx reverse proxy |
| Process manager | gunicorn (3 workers) |
| Static + media | Served by Plesk Nginx directly from bind-mounted host folders |

**What you must have before starting:**
1. A Plesk Obsidian server you control, at IP `203.0.113.42`, reachable via SSH as root (or a user with `sudo`).
2. The Plesk **Docker** extension installed (Plesk → Extensions → Docker → Install). It's free.
3. A domain `DOMAIN.example.com` with an A record pointing to `203.0.113.42`. Wait ~10 minutes after creating the record so DNS propagates.
4. The Plesk **Let's Encrypt** extension installed.
5. SSH access to the server (you'll need to `ssh root@203.0.113.42` for parts of this).
6. The GitHub repository `git@github.com:pnigroh/raffle-campaign.git` accessible. If your repo is private, you'll generate a deploy key on the server in Phase 2.

---

## Phase 1 — Make the codebase production-ready (local, on your dev machine)

The current `Dockerfile` + `docker-compose.yml` are wired for dev (Django's `runserver`, `DEBUG=True`, no real `SECRET_KEY`). This phase adds a parallel production stack without breaking dev.

### Task 1.1 — Add gunicorn to the dependencies

- [ ] Edit `requirements.txt`. Add this line at the bottom:

```
gunicorn>=21.2.0
```

### Task 1.2 — Create a production-only Dockerfile

- [ ] Create `Dockerfile.prod` at the repo root:

```dockerfile
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/db /app/staticfiles /app/media

EXPOSE 8000

# Production: gunicorn behind Plesk's Nginx reverse proxy.
# 3 workers handles a small giveaway form comfortably; bump if you see queueing.
CMD ["sh", "-c", "\
  python manage.py migrate --noinput && \
  python manage.py collectstatic --noinput && \
  exec gunicorn raffle_project.wsgi:application \
       --bind 0.0.0.0:8000 \
       --workers 3 \
       --access-logfile - \
       --error-logfile - \
       --log-level info \
"]
```

### Task 1.3 — Create the production compose file

- [ ] Create `docker-compose.prod.yml` at the repo root:

```yaml
name: raffle-campaign-prod

services:
  web:
    build:
      context: .
      dockerfile: Dockerfile.prod
    image: raffle-campaign-prod:latest
    container_name: raffle-prod
    restart: unless-stopped
    ports:
      - "127.0.0.1:8500:8000"  # bind to localhost only; Plesk Nginx proxies to it
    env_file: .env.prod
    volumes:
      - ./prod-data/db:/app/db
      - ./prod-data/media:/app/media
      - ./prod-data/staticfiles:/app/staticfiles
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/dashboard/login/')"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 30s
```

Notes:
- `restart: unless-stopped` keeps the container up across reboots.
- Port binds to `127.0.0.1:8500` so the container is reachable ONLY from the Plesk Nginx reverse proxy (not exposed to the public internet directly).
- Three host-mounted folders (`prod-data/db`, `prod-data/media`, `prod-data/staticfiles`) survive container rebuilds.
- The healthcheck targets `/dashboard/login/` because `/` returns 404 (no root route).

### Task 1.4 — Augment `settings.py` for proxy-aware HTTPS

- [ ] Open `raffle_project/settings.py`. Find the line `ALLOWED_HOSTS_ENV = os.environ.get(...)` (around line 27). Just below it (before any other production-relevant blocks), add:

```python
# Production-only security knobs. All driven by env vars so dev stays unaffected.
CSRF_TRUSTED_ORIGINS = [
    o.strip() for o in os.environ.get('CSRF_TRUSTED_ORIGINS', '').split(',')
    if o.strip()
]

if not DEBUG:
    # Behind Plesk Nginx, which terminates TLS and sets X-Forwarded-Proto: https.
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    USE_X_FORWARDED_HOST = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    # Plesk handles HSTS at the Nginx layer; leave Django's HSTS off to avoid
    # double headers. Re-enable here if you ever serve directly without Plesk.
```

### Task 1.5 — Generate a real production SECRET_KEY

- [ ] On your dev machine, generate a fresh 50-character secret:

```bash
docker exec raffle-web python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

Copy the output — that's `PROD_SECRET_KEY` for the env file in Phase 3.

### Task 1.6 — Add `.env.prod` to `.gitignore`

- [ ] Edit `.gitignore` and add:

```
.env.prod
prod-data/
```

This prevents accidentally committing your production secret + data to git.

### Task 1.7 — Commit the production scaffolding

- [ ] Stage and commit the new files:

```bash
cd /home/elgran/Projects/raffle-campaign
git add Dockerfile.prod docker-compose.prod.yml requirements.txt raffle_project/settings.py .gitignore
git commit -m "feat(deploy): production Dockerfile + compose + proxy-aware settings"
git push origin main
```

### Task 1.8 — Export the dev data for transfer

- [ ] On your dev machine:

```bash
cd /home/elgran/Projects/raffle-campaign
mkdir -p /tmp/raffle-bootstrap
# Copy the live SQLite file. The dev container has the .sqlite3 inside; we copy from the repo root
# (which is bind-mounted into the container, so the file is identical).
cp db.sqlite3 /tmp/raffle-bootstrap/db.sqlite3
# Tar the media (campaign logos + submission images)
tar -czf /tmp/raffle-bootstrap/media.tar.gz -C . media
ls -la /tmp/raffle-bootstrap/
```

Expected: `db.sqlite3` ~270KB and `media.tar.gz` ~1.5MB.

---

## Phase 2 — Provision the Plesk server (SSH session)

### Task 2.1 — SSH into the server and install Docker if it isn't already

```bash
ssh root@203.0.113.42
```

Verify Docker is present (the Plesk Docker extension installs it):

```bash
docker --version
docker compose version
```

Expected: both commands print versions. If `docker compose` is missing, install the compose plugin:

```bash
# Debian/Ubuntu
apt-get update && apt-get install -y docker-compose-plugin
# AlmaLinux/RHEL
dnf install -y docker-compose-plugin
```

### Task 2.2 — Create a dedicated subscription/domain in Plesk

In the Plesk web UI:

1. Log in to `https://203.0.113.42:8443/` (Plesk's admin URL — accept the self-signed cert warning the first time).
2. **Subscriptions → Add Subscription** → set domain `DOMAIN.example.com`, FTP/SSH user `raffleapp`, strong password.
3. Click **OK**. Plesk creates `/var/www/vhosts/DOMAIN.example.com/` and provisions the FTP + SSH user.

This gives you a clean per-domain directory tree that Plesk Nginx can manage independently.

### Task 2.3 — Clone the repository onto the server

The repo at `git@github.com:pnigroh/raffle-campaign.git` is private. Generate a deploy key:

```bash
ssh root@203.0.113.42
su - raffleapp
ssh-keygen -t ed25519 -C "raffleapp@DOMAIN.example.com" -f ~/.ssh/id_ed25519 -N ""
cat ~/.ssh/id_ed25519.pub
```

Copy the printed public key.

In a browser, go to **GitHub → repo pnigroh/raffle-campaign → Settings → Deploy keys → Add deploy key**. Title: `Plesk prod`. Paste the public key. Leave "Allow write access" UNCHECKED (read-only is enough for pulls). Click **Add key**.

Back on the server:

```bash
cd ~
git clone git@github.com:pnigroh/raffle-campaign.git
cd raffle-campaign
git log --oneline | head -3
```

Expected: latest 3 commit lines, top one should be your latest push from Phase 1.

### Task 2.4 — Create persistent data directories

```bash
cd ~/raffle-campaign
mkdir -p prod-data/db prod-data/media prod-data/staticfiles
chmod 750 prod-data prod-data/db prod-data/media prod-data/staticfiles
```

### Task 2.5 — Upload the dev data to the server

From your **dev machine** (a new terminal, not the SSH session):

```bash
# Copy the SQLite DB
scp /tmp/raffle-bootstrap/db.sqlite3 raffleapp@203.0.113.42:/var/www/vhosts/DOMAIN.example.com/raffle-campaign/prod-data/db/db.sqlite3

# Copy the media archive
scp /tmp/raffle-bootstrap/media.tar.gz raffleapp@203.0.113.42:/tmp/media.tar.gz
```

Back in the **SSH session as raffleapp**:

```bash
cd ~/raffle-campaign/prod-data
tar -xzf /tmp/media.tar.gz --strip-components=1 -C media
ls -la db/ media/ | head -10
rm /tmp/media.tar.gz
```

Expected: `db/db.sqlite3` present (~270KB), and `media/` contains the campaign logos / submission images.

---

## Phase 3 — Production environment file

### Task 3.1 — Create `.env.prod` on the server

In the SSH session:

```bash
cd ~/raffle-campaign
nano .env.prod
```

Paste this content (substituting your values for `PROD_SECRET_KEY` and `DOMAIN.example.com`):

```
SECRET_KEY=PROD_SECRET_KEY
DEBUG=False
ALLOWED_HOSTS=DOMAIN.example.com,www.DOMAIN.example.com,127.0.0.1
CSRF_TRUSTED_ORIGINS=https://DOMAIN.example.com,https://www.DOMAIN.example.com
RAFFLE_CAMPAIGN_WEB_PORT=8500
```

Save (Ctrl+O, Enter) and exit (Ctrl+X).

Secure the file:

```bash
chmod 600 .env.prod
ls -la .env.prod
```

Expected permissions: `-rw-------`.

---

## Phase 4 — First build + boot

### Task 4.1 — Build the image and start the container

```bash
cd ~/raffle-campaign
docker compose -f docker-compose.prod.yml build
docker compose -f docker-compose.prod.yml up -d
```

Wait ~30 seconds, then:

```bash
docker compose -f docker-compose.prod.yml logs --tail 30
```

Expected (look for these lines):
- `Applying campaigns.0008_backfill_legacy_audit_flags... OK` (or "No migrations to apply" if already applied)
- `XX static files copied to '/app/staticfiles'`
- `Listening at: http://0.0.0.0:8000`
- `Booting worker with pid: …` × 3

### Task 4.2 — Curl-verify locally (still inside the SSH session)

```bash
curl -s -o /dev/null -w "submission_form: %{http_code}\n" http://127.0.0.1:8500/submit/futboleros-bn-hn/
curl -s -o /dev/null -w "admin login:    %{http_code}\n" http://127.0.0.1:8500/admin/login/
curl -s -o /dev/null -w "dashboard:      %{http_code}\n" http://127.0.0.1:8500/dashboard/
```

Expected: `200`, `200`, `302` (dashboard redirects to login). If you see `400 Bad Request`, your `ALLOWED_HOSTS` doesn't include `127.0.0.1` — fix `.env.prod` and `docker compose restart web`.

### Task 4.3 — Verify the imported data is intact

```bash
docker exec raffle-prod python manage.py shell -c "
from campaigns.models import Campaign, Prize, Submission, Raffle
from django.contrib.auth import get_user_model
U = get_user_model()
print(f'Campaigns:    {Campaign.objects.count()}')
print(f'Prizes:       {Prize.objects.count()}')
print(f'Submissions:  {Submission.objects.count()}')
print(f'Raffles:      {Raffle.objects.count()}')
print(f'Users:        {U.objects.count()}')
"
```

Expected:

```
Campaigns:    1
Prizes:       1
Submissions:  8
Raffles:      2
Users:        2
```

If those counts match, your dev data is live in production.

### Task 4.4 — Reset the production admin password

The dev admin password (`admin123`) is now in your production DB. Rotate it immediately:

```bash
docker exec -it raffle-prod python manage.py changepassword admin
# Enter STRONGADMIN_PW twice
```

Do the same for `manager` if you want to keep that test account around (or delete it):

```bash
docker exec -it raffle-prod python manage.py changepassword manager
# Or to delete it:
# docker exec raffle-prod python manage.py shell -c "from django.contrib.auth import get_user_model; get_user_model().objects.filter(username='manager').delete()"
```

---

## Phase 5 — Plesk Nginx reverse proxy + static/media

### Task 5.1 — Wire Plesk Nginx to forward to the container

In the Plesk web UI:

1. Go to **Domains → DOMAIN.example.com → Apache & nginx Settings**.
2. Scroll to **Additional nginx directives**.
3. Paste this block:

```nginx
# Forward dynamic Django traffic to the gunicorn container on localhost:8500
location / {
    proxy_pass http://127.0.0.1:8500;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_redirect off;
    proxy_buffering on;
    proxy_read_timeout 30s;
}

# Serve static files directly from the bind-mounted host folder (faster + no Django round-trip)
location /static/ {
    alias /var/www/vhosts/DOMAIN.example.com/raffle-campaign/prod-data/staticfiles/;
    expires 7d;
    add_header Cache-Control "public, immutable";
}

# Serve media uploads directly (user-uploaded campaign logos, submission photos)
location /media/ {
    alias /var/www/vhosts/DOMAIN.example.com/raffle-campaign/prod-data/media/;
    expires 1d;
    add_header Cache-Control "public";
}

# Long client_max_body_size for submission image uploads (10 MB ceiling)
client_max_body_size 10m;
```

4. Click **OK**. Plesk reloads nginx.

### Task 5.2 — Verify via the domain

From any machine:

```bash
curl -I http://DOMAIN.example.com/submit/futboleros-bn-hn/
curl -I http://DOMAIN.example.com/static/campaigns/landing/bg_desktop.png
curl -I http://DOMAIN.example.com/static/css/brand.css
```

Expected: all three return `HTTP/1.1 200 OK` (or `301` if Plesk auto-redirects to HTTPS — that's fine and means SSL is already wired).

### Task 5.3 — Issue a Let's Encrypt certificate

In Plesk:

1. **Domains → DOMAIN.example.com → SSL/TLS Certificates → Install a free basic certificate provided by Let's Encrypt**.
2. Check: **Secure the wildcard domain** (off if you don't have wildcard DNS), **Include www.DOMAIN.example.com**, **Assign certificate**.
3. Click **Get it free**. Plesk handles DNS challenge automatically.
4. In **Hosting Settings**, toggle **Permanent SEO-safe 301 redirect from HTTP to HTTPS** to **On**.

Verify:

```bash
curl -I https://DOMAIN.example.com/submit/futboleros-bn-hn/
```

Expected: `HTTP/2 200`.

---

## Phase 6 — End-to-end smoke check

Open `https://DOMAIN.example.com/submit/futboleros-bn-hn/` in a real browser. Walk through:

1. **Welcome step** — bike + sky BG, logo top-left (desktop) or top-center (mobile), ¡BIENVENIDO! + EMPEZAR pill.
2. Click EMPEZAR — form step, red pill titulars, fields.
3. Submit a real test entry with a small image upload (use any small JPEG).
4. Trivia step — pick the correct answer (option 3).
5. Success step — `¡ERES UN CRACK!` titular + FINALIZAR.

Then, in another tab: `https://DOMAIN.example.com/dashboard/login/`. Sign in as `admin` with `STRONGADMIN_PW`. Confirm:

- Dashboard renders with the Promo-Domo brand.
- Campaign list shows "Futboleros Nube Blanca y Rosal - Honduras".
- The new submission you just created appears in the submissions table.
- Run an audit verification by clicking **Auditoría** on an existing raffle — confirm the green "Auditoría verificada" banner.

If anything fails the smoke check, jump to the **Troubleshooting** section below.

---

## Phase 7 — Backups

### Task 7.1 — Create a backup script on the server

```bash
ssh root@203.0.113.42
mkdir -p /var/backups/raffle
cat > /usr/local/bin/raffle-backup.sh <<'EOF'
#!/bin/bash
set -e
TS=$(date +%Y-%m-%d-%H%M)
DEST=/var/backups/raffle
SRC=/var/www/vhosts/DOMAIN.example.com/raffle-campaign/prod-data

mkdir -p "$DEST"

# 1. SQLite: copy with sqlite3 .backup to get a consistent snapshot even if the
#    DB is being written to mid-backup.
docker exec raffle-prod sqlite3 /app/db/db.sqlite3 ".backup '/app/db/snapshot.sqlite3'"
cp "$SRC/db/snapshot.sqlite3" "$DEST/db-$TS.sqlite3"
rm "$SRC/db/snapshot.sqlite3"

# 2. Media: tar the uploads folder.
tar -czf "$DEST/media-$TS.tar.gz" -C "$SRC" media

# 3. Retention: keep 14 days of daily backups.
find "$DEST" -name "db-*.sqlite3" -mtime +14 -delete
find "$DEST" -name "media-*.tar.gz" -mtime +14 -delete

echo "Backup complete: $DEST/db-$TS.sqlite3 + $DEST/media-$TS.tar.gz"
EOF

chmod +x /usr/local/bin/raffle-backup.sh
```

Replace `DOMAIN.example.com` in the script with your real domain before saving.

### Task 7.2 — Schedule the backup nightly via cron

```bash
crontab -e
```

Add this line (runs every night at 03:15 server time):

```
15 3 * * * /usr/local/bin/raffle-backup.sh >> /var/log/raffle-backup.log 2>&1
```

Save and exit.

### Task 7.3 — Test the backup script once manually

```bash
/usr/local/bin/raffle-backup.sh
ls -la /var/backups/raffle/
```

Expected: two new files dated today (db-YYYY-MM-DD-HHMM.sqlite3 and media-…tar.gz). If `sqlite3` is missing inside the container: `docker exec raffle-prod apt-get install -y sqlite3` and re-run.

### Task 7.4 — Off-server backup (recommended)

The local backups protect against in-container corruption but not against a full server loss. Sync them off-box:

Option A — `rsync` to another VPS (cheapest):

```bash
# On the Plesk server, add to crontab (after the backup line):
30 3 * * * rsync -az --delete /var/backups/raffle/ backup@OTHER_HOST:/backups/raffle/
```

Option B — Upload to S3-compatible storage (Backblaze B2, Wasabi, AWS S3):

```bash
apt-get install -y rclone
rclone config  # interactive — set up a remote called "b2"
# Add to crontab:
30 3 * * * rclone sync /var/backups/raffle/ b2:raffle-backups/ --delete-during
```

Either way, verify weekly that the off-box copy is current.

---

## Phase 8 — Updating the production server (future deploys)

When you push new commits to `origin/main`, deploy them with:

```bash
ssh raffleapp@203.0.113.42
cd ~/raffle-campaign
git pull origin main
docker compose -f docker-compose.prod.yml build
docker compose -f docker-compose.prod.yml up -d
docker compose -f docker-compose.prod.yml logs --tail 50
```

The `Dockerfile.prod`'s `CMD` runs `migrate` + `collectstatic` on every container start, so new migrations apply automatically. Static file changes (new PNGs, new CSS) land in `prod-data/staticfiles/` and are served by Plesk Nginx with the 7-day cache header.

If you want a tighter window:

```bash
# Pull, build, and replace the container in one go:
cd ~/raffle-campaign && \
git pull origin main && \
docker compose -f docker-compose.prod.yml build && \
docker compose -f docker-compose.prod.yml up -d --force-recreate
```

Downtime is ~5-15 seconds while the container restarts.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `400 Bad Request — DisallowedHost` | `ALLOWED_HOSTS` env var doesn't include the requested host | Edit `.env.prod`, ensure `DOMAIN.example.com` is in `ALLOWED_HOSTS`, `docker compose -f docker-compose.prod.yml restart web` |
| `502 Bad Gateway` from Plesk | Container not running, or port 8500 not bound | `docker ps` to check, `docker compose logs --tail 50` for errors |
| Static files (CSS, PNGs) return 404 | `collectstatic` didn't run OR the Nginx alias path is wrong | `docker exec raffle-prod python manage.py collectstatic --noinput`; verify `prod-data/staticfiles/` exists and has files; check the Plesk `location /static/` `alias` path matches |
| Submission image upload fails with "413 Request Entity Too Large" | Plesk Nginx body limit too small | Bump `client_max_body_size 10m;` higher in the Plesk Additional nginx directives block |
| Browser warns "Not Secure" / certificate error | Let's Encrypt cert not issued yet, or DNS not pointing at the server | Wait 10 minutes after DNS, then re-run the Plesk Let's Encrypt issuance |
| CSRF verification failed on form submit | `CSRF_TRUSTED_ORIGINS` doesn't include the request scheme+host | Edit `.env.prod`, ensure `https://DOMAIN.example.com` is in `CSRF_TRUSTED_ORIGINS`, restart container |
| Mixed-content warnings in browser | Plesk isn't setting `X-Forwarded-Proto: https` | Make sure the Plesk Nginx block in Task 5.1 has `proxy_set_header X-Forwarded-Proto $scheme;` |

### Useful log paths

| Source | Path |
|---|---|
| Plesk Nginx access log | `/var/log/plesk-nginx/DOMAIN.example.com.access.log` |
| Plesk Nginx error log | `/var/log/plesk-nginx/DOMAIN.example.com.error.log` |
| Container stdout/stderr (gunicorn) | `docker compose -f docker-compose.prod.yml logs -f web` |
| Container shell access | `docker exec -it raffle-prod bash` |
| SQLite DB shell | `docker exec -it raffle-prod python manage.py dbshell` |
| Django shell | `docker exec -it raffle-prod python manage.py shell` |

---

## Appendix A — Data audit on the production server

Spot-check that everything migrated cleanly:

```bash
docker exec raffle-prod python manage.py shell -c "
from campaigns.models import Campaign, Prize, Submission, Raffle, RaffleWinner
from django.contrib.auth.models import Group

print('=== Campaigns ===')
for c in Campaign.objects.all():
    print(f'  id={c.id}  {c.name!r}  active={c.is_active}  managers={c.managers.count()}')

print()
print('=== Prizes ===')
for p in Prize.objects.all():
    print(f'  id={p.id}  {p.name!r}  qty={p.quantity}  campaign={p.campaign.name!r}')

print()
print('=== Raffles + audit ===')
for r in Raffle.objects.all():
    auditable = 'yes' if r.seed else 'legacy/no-seed'
    print(f'  id={r.id}  conducted={r.conducted_at}  winners={r.winners.count()}  audit={auditable}')

print()
print('=== Campaign Managers group ===')
g = Group.objects.get(name='Campaign Managers')
print(f'  perms={g.permissions.count()}  members={g.user_set.count()}')
"
```

Expected output mirrors your dev DB (1 campaign, 1 prize, 2 raffles — one with `audit=yes`, one `legacy/no-seed`, the Campaign Managers group with 22 perms and 1 member if you kept the `manager` user).

---

## Appendix B — Asset inventory check

Confirm all the static + media assets transferred:

```bash
# Static files (should be ~10MB total)
du -sh /var/www/vhosts/DOMAIN.example.com/raffle-campaign/prod-data/staticfiles
find /var/www/vhosts/DOMAIN.example.com/raffle-campaign/prod-data/staticfiles/campaigns/landing -name "*.png" | wc -l
# Expected: 15 (14 designer PNGs + logo_nube.png)

# Brand assets (Promo-Domo)
ls /var/www/vhosts/DOMAIN.example.com/raffle-campaign/prod-data/staticfiles/brand/
# Expected: dodo.svg, dodo-light.svg, favicon.svg

# Andreas font for the landing
ls /var/www/vhosts/DOMAIN.example.com/raffle-campaign/prod-data/staticfiles/campaigns/fonts/
# Expected: Andreas.ttf

# Media (campaign logos + any submission images)
du -sh /var/www/vhosts/DOMAIN.example.com/raffle-campaign/prod-data/media
```

If any of these is missing, re-run `docker exec raffle-prod python manage.py collectstatic --noinput` and re-extract the media tarball.

---

## Appendix C — Rollback procedure (if a deploy goes wrong)

```bash
ssh raffleapp@203.0.113.42
cd ~/raffle-campaign

# 1. Stop the broken container
docker compose -f docker-compose.prod.yml down

# 2. Roll the code back to the previous commit
git log --oneline | head -10   # find the SHA to roll to
git checkout <PREVIOUS_SHA>

# 3. Restore the DB from the latest backup if migrations corrupted data
cp /var/backups/raffle/db-YYYY-MM-DD-HHMM.sqlite3 prod-data/db/db.sqlite3

# 4. Rebuild and start
docker compose -f docker-compose.prod.yml build
docker compose -f docker-compose.prod.yml up -d
```

Once stabilized, fix the underlying bug on the `main` branch and redeploy with the normal update flow (Phase 8).

---

## Summary checklist

Tick these as you go:

- [ ] **Phase 1** — `Dockerfile.prod`, `docker-compose.prod.yml`, `gunicorn` in requirements, `settings.py` proxy-aware block, `.env.prod` gitignored, secret generated, dev data exported, all committed
- [ ] **Phase 2** — Server SSH ✓, Docker present ✓, Plesk subscription for `DOMAIN.example.com` ✓, repo cloned via deploy key, dev DB + media uploaded
- [ ] **Phase 3** — `.env.prod` on server, mode `600`
- [ ] **Phase 4** — `docker compose build` + `up -d` succeed, logs clean, data verified, admin password rotated
- [ ] **Phase 5** — Plesk Nginx forwards `/` to `127.0.0.1:8500`, serves `/static/` and `/media/` directly, Let's Encrypt cert issued, HTTPS redirect on
- [ ] **Phase 6** — Browser smoke check: submission form (5 steps), dashboard login, audit page renders + verifies
- [ ] **Phase 7** — `/usr/local/bin/raffle-backup.sh` scheduled at `15 3 * * *`, first manual run produced a `.sqlite3` + `.tar.gz` in `/var/backups/raffle/`, off-box sync configured
- [ ] **Phase 8** — Confirmed the update flow works by pushing a trivial commit (e.g., a README typo fix) and pulling/rebuilding on the server

Once every box is ticked, the server is production-ready.
