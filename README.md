# 🎰 Raffle Campaign Manager

A Django-based campaign and raffle management system that allows you to create campaigns, collect participant submissions via a public form, and conduct segmented raffles with exportable results.

---

## Features

- **Campaign Management** — create campaigns with start/end dates, active status, and configurable code validation
- **Submission Codes** — bulk-import codes via CSV; campaigns can optionally require a valid code before accepting a submission
- **Public Submission Form** — clean, public-facing form collecting name, state, county, phone, email, and submission code
- **Dashboard** — overview of active campaigns, submission counts, and recent activity
- **Segmented Raffles** — filter the participant pool by state, county, and date range before drawing; live participant count via AJAX
- **Multi-Prize Draws** — assign winner quantities per prize in a single raffle run; no duplicate winners
- **CSV Export** — export winners or all submissions to CSV at any time
- **Django Unfold Admin** — modern, beautiful admin UI with custom navigation sidebar

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Framework | Django 4.2 |
| Database | SQLite (dev) / PostgreSQL (prod) |
| Admin UI | Django Unfold |
| Forms | django-crispy-forms + crispy-bootstrap5 |
| Frontend | Bootstrap 5 (CDN) |

---

## Local Development

### 1. Clone the repository

```bash
git clone https://github.com/pnigroh/raffle-campaign-manager.git
cd raffle-campaign-manager
```

### 2. Create a virtual environment

```bash
python3 -m venv venv
source venv/bin/activate      # Linux/macOS
venv\Scripts\activate         # Windows
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment

```bash
cp .env.example .env
# Edit .env with your values
```

### 5. Apply migrations

```bash
python3 manage.py migrate
```

### 6. Create a superuser

```bash
# Quick default (admin / admin123) — development only
python3 manage.py create_superuser_default

# Or create your own
python3 manage.py createsuperuser
```

### 7. Run the development server

```bash
python3 manage.py runserver
```

Visit `http://127.0.0.1:8000/dashboard/` and log in.

---

## URL Reference

| URL | Access | Description |
|-----|--------|-------------|
| `/admin/` | Staff | Django Unfold admin panel |
| `/dashboard/` | Staff | Campaign dashboard |
| `/dashboard/login/` | Public | Staff login page |
| `/dashboard/campaign/<id>/` | Staff | Campaign detail + submissions |
| `/dashboard/campaign/<id>/raffle/` | Staff | Run a raffle |
| `/dashboard/campaign/<id>/import-codes/` | Staff | CSV code import |
| `/dashboard/campaign/<id>/export/` | Staff | Export submissions CSV |
| `/dashboard/raffle/<id>/results/` | Staff | View raffle results |
| `/dashboard/raffle/<id>/export/` | Staff | Export winners CSV |
| `/submit/<campaign-slug>/` | Public | Participant submission form |
| `/submit/<campaign-slug>/success/` | Public | Post-submission thank-you page |

---

## Data Model

```
Campaign
├── Prize (many)
├── SubmissionCode (many)
├── Submission (many)
│   └── linked to one SubmissionCode (optional)
└── Raffle (many)
    └── RaffleWinner (many)
        ├── → Submission
        └── → Prize
```

---

## Importing Submission Codes

Navigate to **Dashboard → Campaign → Import Codes** and upload a CSV file.

Accepted formats:

```csv
code
ABC123
DEF456
GHI789
```

or a plain single-column file (no header):

```
ABC123
DEF456
GHI789
```

---

## Running a Raffle

1. Open **Dashboard → Campaign → Run Raffle**
2. Apply optional segment filters (state, county, date range) — the live counter updates automatically
3. Set winner quantities for each prize
4. Add optional notes
5. Click **Confirm & Run Raffle**
6. View results and download the winners CSV

> ⚠️ Raffles are permanent records. Each run creates a new `Raffle` object with its own set of winners.

---

## Deploying to a Production Server

This guide covers deploying to an **Ubuntu 22.04** VPS (DigitalOcean, Hetzner, AWS EC2, etc.) using **PostgreSQL**, **Gunicorn**, and **Nginx**.

### Prerequisites

- A server running Ubuntu 22.04+
- A domain name pointed to the server's IP
- SSH access as a non-root user with `sudo` privileges

---

### Step 1 — Install system dependencies

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-pip python3-venv \
    postgresql postgresql-contrib \
    nginx git curl
```

---

### Step 2 — Create a PostgreSQL database

```bash
sudo -u postgres psql
```

```sql
CREATE DATABASE raffle_db;
CREATE USER raffle_user WITH PASSWORD 'strong_password_here';
ALTER ROLE raffle_user SET client_encoding TO 'utf8';
ALTER ROLE raffle_user SET default_transaction_isolation TO 'read committed';
ALTER ROLE raffle_user SET timezone TO 'UTC';
GRANT ALL PRIVILEGES ON DATABASE raffle_db TO raffle_user;
\q
```

---

### Step 3 — Clone the project

```bash
cd /var/www
sudo git clone https://github.com/pnigroh/raffle-campaign-manager.git raffle
sudo chown -R $USER:$USER /var/www/raffle
cd /var/www/raffle
```

---

### Step 4 — Create the virtual environment and install dependencies

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install gunicorn psycopg2-binary
```

---

### Step 5 — Configure the environment file

```bash
cp .env.example .env
nano .env
```

Fill in the following:

```env
SECRET_KEY=your-very-long-random-secret-key-here
DEBUG=False
ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com

DATABASE_URL=postgres://raffle_user:strong_password_here@localhost/raffle_db
```

> **Tip:** Generate a secret key with:
> ```bash
> python3 -c "import secrets; print(secrets.token_urlsafe(50))"
> ```

You also need to update `raffle_project/settings.py` to read `DATABASE_URL`. Add this block after the default `DATABASES` config:

```python
import os
DATABASE_URL = os.environ.get('DATABASE_URL')
if DATABASE_URL and DATABASE_URL.startswith('postgres://'):
    import urllib.parse as urlparse
    url = urlparse.urlparse(DATABASE_URL)
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': url.path[1:],
            'USER': url.username,
            'PASSWORD': url.password,
            'HOST': url.hostname,
            'PORT': url.port or 5432,
        }
    }
```

Or simply install `dj-database-url` and use:

```bash
pip install dj-database-url
```

```python
# settings.py
import dj_database_url
DATABASES = {'default': dj_database_url.config(default=os.environ.get('DATABASE_URL'))}
```

---

### Step 6 — Run migrations and collect static files

```bash
source venv/bin/activate
python3 manage.py migrate
python3 manage.py collectstatic --noinput
python3 manage.py createsuperuser
```

---

### Step 7 — Configure Gunicorn as a systemd service

Create the service file:

```bash
sudo nano /etc/systemd/system/raffle.service
```

Paste:

```ini
[Unit]
Description=Raffle Campaign Manager - Gunicorn
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=/var/www/raffle
EnvironmentFile=/var/www/raffle/.env
ExecStart=/var/www/raffle/venv/bin/gunicorn \
    --access-logfile - \
    --workers 3 \
    --bind unix:/run/raffle.sock \
    raffle_project.wsgi:application

[Install]
WantedBy=multi-user.target
```

Enable and start it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable raffle
sudo systemctl start raffle
sudo systemctl status raffle   # should show "active (running)"
```

---

### Step 8 — Configure Nginx

```bash
sudo nano /etc/nginx/sites-available/raffle
```

Paste:

```nginx
server {
    listen 80;
    server_name yourdomain.com www.yourdomain.com;

    client_max_body_size 10M;

    location = /favicon.ico { access_log off; log_not_found off; }

    location /static/ {
        root /var/www/raffle;
    }

    location /media/ {
        root /var/www/raffle;
    }

    location / {
        include proxy_params;
        proxy_pass http://unix:/run/raffle.sock;
    }
}
```

Enable the site:

```bash
sudo ln -s /etc/nginx/sites-available/raffle /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

---

### Step 9 — Enable HTTPS with Let's Encrypt

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d yourdomain.com -d www.yourdomain.com
```

Certbot will automatically update your Nginx config and set up auto-renewal.

---

### Step 10 — Set correct file permissions

```bash
sudo chown -R www-data:www-data /var/www/raffle/staticfiles
sudo chown -R www-data:www-data /var/www/raffle/media
sudo chmod 600 /var/www/raffle/.env
```

---

### Deployment Checklist

- [ ] `DEBUG=False` in `.env`
- [ ] Strong `SECRET_KEY` set
- [ ] `ALLOWED_HOSTS` set to your domain
- [ ] PostgreSQL database created and connected
- [ ] `collectstatic` run
- [ ] Gunicorn service running (`systemctl status raffle`)
- [ ] Nginx configured and running
- [ ] HTTPS certificate issued via Certbot
- [ ] Default admin password changed
- [ ] `.env` file permissions restricted (`chmod 600`)
- [ ] Regular database backups configured

---

### Updating the Application

When you push new code to GitHub, SSH into the server and run:

```bash
cd /var/www/raffle
git pull origin main
source venv/bin/activate
pip install -r requirements.txt
python3 manage.py migrate
python3 manage.py collectstatic --noinput
sudo systemctl restart raffle
```

---

## Default Credentials (Development Only)

| Username | Password |
|----------|----------|
| `admin` | `admin123` |

> Change these immediately. Never use defaults in production.

---

## License

MIT — free to use and modify.
