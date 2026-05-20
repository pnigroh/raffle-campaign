# Running raffle-campaign locally

## Quick reference

- **App URL:** http://localhost:8500/dashboard/
- **Admin (Unfold):** http://localhost:8500/admin/
- **Public submission form:** http://localhost:8500/submit/&lt;campaign-slug&gt;/
- **Default dev login:** `admin` / `admin123`
- **Container name:** `raffle-web`
- **Host port:** `8500` (mapped to container `8000`)

## Start / stop

The project uses Docker Compose. The compose file requires `RAFFLE_CAMPAIGN_WEB_PORT` to be set (Mila-bot convention — `8500` is the assigned port for this project).

```bash
cd /home/elgran/Projects/raffle-campaign

# start (detached)
RAFFLE_CAMPAIGN_WEB_PORT=8500 docker compose up -d

# stop
RAFFLE_CAMPAIGN_WEB_PORT=8500 docker compose down

# follow logs
docker logs -f raffle-web
```

On startup the container auto-runs `migrate` and `collectstatic`, then launches `runserver 0.0.0.0:8000`.

## Code reloads

The repo is bind-mounted into the container at `/app`, and `runserver` watches for file changes — Python edits reload automatically with no restart.

Rebuild only when `requirements.txt` or `Dockerfile` changes:

```bash
RAFFLE_CAMPAIGN_WEB_PORT=8500 docker compose up -d --build
```

## Django management commands

Run any `manage.py` command inside the container:

```bash
docker exec -it raffle-web python manage.py <command>

# common ones
docker exec -it raffle-web python manage.py migrate
docker exec -it raffle-web python manage.py createsuperuser
docker exec -it raffle-web python manage.py create_superuser_default   # admin / admin123
docker exec -it raffle-web python manage.py shell
docker exec -it raffle-web python manage.py showmigrations
```

## Health check

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8500/dashboard/login/
# expect: 200
```

## Alternative: run on host Python (no Docker)

```bash
cd /home/elgran/Projects/raffle-campaign
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python3 manage.py migrate
python3 manage.py create_superuser_default
python3 manage.py runserver 0.0.0.0:8000
```

Then visit http://localhost:8000/dashboard/.

## Themes (local dev)

The public submission form and success page render from a theme bundle, not directly from `campaigns/templates/`. Local dev uses `<repo>/themes/<slug>/` as `THEMES_ROOT`.

After `migrate` runs the first time, the default Futboleros theme is auto-populated at `<repo>/themes/futboleros/`. If you wipe the directory, restore it with:

```bash
docker exec raffle-web python manage.py setup_default_theme
```

To test a custom theme without going through the upload UI:
1. Build the bundle layout at `<repo>/themes/<my-slug>/{submission_form.html, submission_success.html, assets/}`.
2. Create the Theme row: `docker exec -it raffle-web python manage.py shell` → `from campaigns.models import Theme; Theme.objects.create(name="X", slug="my-slug")`.
3. Assign a Campaign to it in admin.

## Troubleshooting

- **Port 8500 already in use** — `ss -tlnp | grep 8500` to find the offender, or pick a different `RAFFLE_CAMPAIGN_WEB_PORT`.
- **Container exits immediately** — `docker logs raffle-web` to see the error. The healthcheck hits `/`, which returns 404; this is harmless and is not what stops the container.
- **Static files missing** — re-run collectstatic: `docker exec raffle-web python manage.py collectstatic --noinput`.
- **Database wiped** — the SQLite file lives in the `raffle_db` Docker volume. Recreate with `docker exec raffle-web python manage.py migrate && docker exec raffle-web python manage.py create_superuser_default`.
