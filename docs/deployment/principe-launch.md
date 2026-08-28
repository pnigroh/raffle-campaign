# Launching Príncipe "Te pone en ruedas" on bimbotepremia.com

The generic procedure is in `host-setup.md` → "Adding a new tenant domain". This
is the concrete version for this campaign, which differs in one way: the domain,
theme, campaign, schema and prize all come from one management command instead of
admin clicks.

DNS is already pointed at the droplet. The remaining steps run on the prod host.

## 1. `.env.prod`

Append both hostnames to the two host settings — Django matches `Host` exactly, so
the apex and `www` are distinct entries:

```
ALLOWED_HOSTS=<existing hosts>,bimbotepremia.com,www.bimbotepremia.com
CSRF_TRUSTED_ORIGINS=<existing origins>,https://bimbotepremia.com,https://www.bimbotepremia.com
```

`CSRF_TRUSTED_ORIGINS` is not optional here: the form POSTs over HTTPS, and
without it Django rejects the submission with a 403.

## 2. Reverse proxy + TLS

Add `bimbotepremia.com` and `www.bimbotepremia.com` to the vhost, following the
same pattern as futbolerosnb.com, and issue a certificate for both names. Keep
the `/theme-assets/` alias block from `host-setup.md` — this theme leans on it
(~640 KB of backgrounds, packs and fonts).

Redirect `www` → apex at the proxy. The app resolves campaigns by exact hostname,
so `www` reaching Django directly would 404: only `bimbotepremia.com` has a
`Domain` row.

## 3. Deploy the code and provision

```bash
cd /srv/raffle
git pull
docker compose -f docker-compose.prod.yml up -d --build web
docker exec raffle-prod python manage.py provision_principe
```

`provision_principe` is idempotent — safe to re-run. It creates the `Domain`, the
`Theme` row, copies `campaigns/themes/principe/` into `/app/themes/principe`
(bind-mounted from `/srv/raffle/themes`), creates the campaign with its 8-field
schema and dates, and seeds the 30-bicycle prize.

Pass `--force-theme` to re-copy the theme after a design change; without it an
existing theme directory is left alone.

## 4. Verify

```bash
docker exec raffle-prod python manage.py check     # must report no campaigns.W001
curl -sI https://bimbotepremia.com/                # 302 -> /submit/principe-ruedas-cr/
curl -sI https://bimbotepremia.com/submit/principe-ruedas-cr/                  # 200
curl -sI https://bimbotepremia.com/theme-assets/principe/img/bg_desktop.jpg    # 200
```

A `campaigns.W001` warning means a `Domain` hostname is missing from
`ALLOWED_HOSTS`. It only surfaces through `manage.py check`, never at startup.

The apex redirect comes from `campaigns.views.root_redirect`, which resolves only
when the host has exactly one active campaign. That holds for this domain;
futbolerosnb.com carries two and keeps its existing 404 plus the `/g` and `/h`
short links.

## Operator notes

- **Prizes.** Unlike `provision_futboleros`, this command seeds the prize
  (Bicicleta ×30), because the quantity is printed on the artwork. Adjust it from
  the dashboard rather than by editing the command.
- **Purchase location** is a free-text field, stored as `purchase_place` in
  `Submission.extra_data` and included in the CSV export. If the client later
  supplies a store list, switch that entry in `FORM_SCHEMA` to the `store`
  builtin and add `Store` rows — no template change is needed.
- **Campaign window** is 2026-08-24 → 2026-10-02 23:59. Outside it the form
  renders a closed notice and rejects POSTs. Re-running the command does not
  reset the dates.
