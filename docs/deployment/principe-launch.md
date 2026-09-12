# Launching Príncipe "Te pone en ruedas" on promoprincipe.com

The generic procedure is in `host-setup.md` → "Adding a new tenant domain". This
is the concrete version for this campaign, which differs in one way: the domain,
theme, campaign, schema and prize all come from one management command instead of
admin clicks.

**promoprincipe.com is the canonical hostname.** It replaced bimbotepremia.com,
which now 301s to it — see "Retiring bimbotepremia.com" below. A campaign belongs
to exactly one `Domain` row and the app matches `Host` exactly, so the old name
cannot also serve the form; it has to redirect.

## 0. DNS

Both records are plain `A` records on the droplet:

```
promoprincipe.com.      A   159.223.186.130
www.promoprincipe.com.  A   159.223.186.130
```

Leave them **DNS-only (grey cloud)** in Cloudflare until the certificate is
issued — see step 2.

## 1. `.env.prod`

Append both hostnames to the two host settings — Django matches `Host` exactly, so
the apex and `www` are distinct entries. Keep the bimbotepremia entries too: the
redirect vhost still terminates TLS for that name.

```
ALLOWED_HOSTS=<existing hosts>,promoprincipe.com,www.promoprincipe.com
CSRF_TRUSTED_ORIGINS=<existing origins>,https://promoprincipe.com,https://www.promoprincipe.com
```

`CSRF_TRUSTED_ORIGINS` is not optional here: the form POSTs over HTTPS, and
without it Django rejects the submission with a 403.

## 2. Reverse proxy + TLS

`/etc/nginx/sites-available/promoprincipe` proxies both hostnames to the app and
serves `/static/`, `/media/` and `/theme-assets/` directly. Copy the existing
`bimbotepremia` vhost and change the `server_name`; it already carries the right
shape, including `client_max_body_size 20m` rather than the 10m used for
futbolerosnb — invoice photos come straight off phone cameras, and a rejected
upload is a lost entry.

**The domain sits behind Cloudflare**, which HTTP-01 validation cannot see
through. To issue the certificate, set both records to DNS-only (grey cloud),
run:

```bash
certbot --nginx -d promoprincipe.com -d www.promoprincipe.com
```

then re-enable the proxy. Certbot rewrites the vhost with the TLS listener and
the port-80 redirect, the same shape futbolerosnb.com already has.

`www` must be redirected to the apex at the proxy. The app resolves campaigns by
exact hostname, so `www` reaching Django directly 404s — only
`promoprincipe.com` has a `Domain` row.

## 3. Deploy the code and provision

`/opt/raffle` is a plain file copy of the repo, not a git checkout, so the code
is pushed from a workstation. Sending only git-tracked files keeps local
secrets and build artefacts off the server:

```bash
# from a clean checkout of main, on your workstation
git ls-files -z | rsync -a --files-from=- --from0 \
    ./ root@159.223.186.130:/opt/raffle/
```

`.env.prod` is untracked, so it survives the sync untouched.

```bash
# on the host
cd /opt/raffle
docker compose --env-file .env.prod -f docker-compose.lean.yml up -d --build web
docker exec raffle-prod python manage.py migrate --noinput
docker exec raffle-prod python manage.py provision_principe
```

`--env-file .env.prod` is required: compose interpolates `${POSTGRES_PASSWORD}`
from `.env` or the shell, not from the `env_file:` a service declares, and
without it the stack refuses to start.

`provision_principe` is idempotent — safe to re-run. It creates the `Domain`, the
`Theme` row, copies `campaigns/themes/principe/` into `/app/themes/principe`
(bind-mounted from `/srv/raffle/themes`), creates the campaign with its 8-field
schema and its 14 September – 23 October window, and seeds the 30-bicycle prize.

Pass `--force-theme` to re-copy the theme after a design change; without it an
existing theme directory is left alone.

A re-run deliberately leaves an existing campaign's dates alone, so it cannot
reopen or close a live promo by accident. Moving the window on a campaign that
already exists takes `--reset-dates`, and that is the only thing that will apply
the 14 September – 23 October window to the live row.

On this run the command also **moves** the campaign: it looks the row up by slug
rather than by (domain, slug), so the campaign that already holds the entries is
re-pointed at `promoprincipe.com` instead of a second one being created beside it
on the new name. The output says so — `campaign updated: principe-ruedas-cr
(moved from bimbotepremia.com)`. If two rows already share the slug it refuses to
guess and stops, because it cannot tell which one holds the real entries.

## 4. Verify

```bash
docker exec raffle-prod python manage.py check     # must report no campaigns.W001
curl -sI https://promoprincipe.com/                # 302 -> /submit/principe-ruedas-cr/
curl -sI https://promoprincipe.com/submit/principe-ruedas-cr/                  # 200
curl -sI https://promoprincipe.com/theme-assets/principe/img/bg_desktop.jpg    # 200
curl -sI https://bimbotepremia.com/                # 301 -> https://promoprincipe.com/
```

Confirm the move did not clone the campaign — a second row would split the draw:

```bash
docker exec raffle-prod python manage.py shell -c "
from campaigns.models import Campaign
for c in Campaign.objects.filter(slug='"'"'principe-ruedas-cr'"'"'):
    print(c.pk, c.domain.hostname, c.submissions.count())"
```

One line, on `promoprincipe.com`, with the submission count unchanged from before
the move.

A `campaigns.W001` warning means a `Domain` hostname is missing from
`ALLOWED_HOSTS`. It only surfaces through `manage.py check`, never at startup.
The standing warning for `promo-domo.example` is the fallback `Domain` row the
seed migration creates; it carries no campaigns and is safe to ignore.

The apex redirect comes from `campaigns.views.root_redirect`, which resolves only
when the host has exactly one active campaign. That holds for this domain;
futbolerosnb.com carries two and keeps its existing 404 plus the `/g` and `/h`
short links.

## 5. Retiring bimbotepremia.com

The name is on printed material, so it keeps its DNS, its vhost and its
certificate — it just stops serving. Replace the proxy body of
`/etc/nginx/sites-available/bimbotepremia` with a redirect:

```nginx
server {
    listen 443 ssl;
    server_name bimbotepremia.com www.bimbotepremia.com;
    # ssl_certificate lines left as certbot wrote them
    return 301 https://promoprincipe.com$request_uri;
}
```

`$request_uri` is what makes an old deep link land on the same page rather than
the home page. Renew the certificate as usual; a redirect vhost still needs valid
TLS, because the browser completes the handshake before it ever sees the 301.

Do **not** add a `Domain` row for bimbotepremia.com. Two rows cannot share one
campaign, and a second campaign row on the old name would quietly collect entries
into a promo nobody draws from.

## Operator notes

- **Prizes.** Unlike `provision_futboleros`, this command seeds the prize
  (Bicicleta ×30), because the quantity is printed on the artwork. Adjust it from
  the dashboard rather than by editing the command.
- **Purchase location** is a free-text field, stored as `purchase_place` in
  `Submission.extra_data` and included in the CSV export. If the client later
  supplies a store list, switch that entry in `FORM_SCHEMA` to the `store`
  builtin and add `Store` rows — no template change is needed.
- **Campaign window** is 2026-09-14 → 2026-10-23 23:59, matching the dates in
  the page footer. Outside it the form renders a closed notice and rejects
  POSTs. A plain re-run deliberately does *not* touch the dates, so it cannot
  reopen or close a live campaign by surprise; pass `--reset-dates` to move an
  existing campaign's window to the values in the command.

## Capacity

The previous campaign produced 2.9 GB of photos from 1228 submissions — roughly
2.4 MB each, straight off phone cameras. The droplet has a single 24 GB disk
shared by the database, the media, and three nightly backup snapshots, and it
has run out of space once before. Watch `df -h /` during the campaign: at the
same rate, about 6000 entries would fill what is currently free.
