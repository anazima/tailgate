# Texas News Curator

Self-hosted tool that pulls Texas news RSS feeds, scores stories with Claude for a
Texas / Dallas Cowboys Facebook page, and turns the best ones into ready-to-post
title + description + image. The owner opens the dashboard, copies the text,
downloads the image, and posts manually. See `CLAUDE.md` for the full spec.

## Local development

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # fill in ANTHROPIC_API_KEY and DASHBOARD_PASSWORD
python manage.py migrate        # SQLite by default; seeds the 11 Texas sources
python manage.py runserver      # http://127.0.0.1:8100  (port pinned in manage.py)
python manage.py createsuperuser   # for /admin/ (source management)
```

Run the pipeline by hand:

```bash
python manage.py fetch_feeds        # RSS → Story rows + clustering
python manage.py score_stories      # Claude scoring (Haiku), hides politics / live sports
python manage.py generate_content   # image + post text (Sonnet) for stories ≥ threshold
python manage.py run_pipeline       # all of the above, in order
```

Tests and lint:

```bash
pytest
ruff check . && ruff format --check .
```

## Environment variables

| Variable | Default | Notes |
|---|---|---|
| `SECRET_KEY` | — | required in production |
| `DEBUG` | `true` | set `false` on the VPS |
| `ALLOWED_HOSTS` | `127.0.0.1,localhost` | comma-separated |
| `DASHBOARD_PASSWORD` | empty | empty = no login gate (dev only) |
| `DB_ENGINE` | `sqlite` | `postgres` on the VPS |
| `POSTGRES_DB/USER/PASSWORD/HOST/PORT` | — | used when `DB_ENGINE=postgres` |
| `ANTHROPIC_API_KEY` | — | required for scoring/generation |
| `SCORING_MODEL` | `claude-haiku-4-5` | Haiku-class |
| `GENERATION_MODEL` | `claude-sonnet-5` | Sonnet-class |
| `GENERATION_THRESHOLD` | `12` | importance + shareability needed to generate |
| `GENERATE_REEL_SCRIPT` | `false` | also produce a ~100-word reel narration |

## Deployment (single Linux VPS, Ubuntu 24.04)

### 1. System packages and app user

```bash
sudo apt install -y python3.12 python3.12-venv postgresql-16 nginx
sudo adduser --system --group --home /opt/texas-news texasnews
sudo -u postgres psql -c "CREATE USER texas_news WITH PASSWORD 'change-me';"
sudo -u postgres psql -c "CREATE DATABASE texas_news OWNER texas_news;"
```

### 2. App checkout

```bash
sudo -u texasnews git clone <repo> /opt/texas-news/app
cd /opt/texas-news/app
sudo -u texasnews python3.12 -m venv .venv
sudo -u texasnews .venv/bin/pip install -r requirements.txt
sudo -u texasnews cp .env.example .env    # edit: DEBUG=false, DB_ENGINE=postgres, SECRET_KEY, ALLOWED_HOSTS, keys
sudo -u texasnews .venv/bin/python manage.py migrate
sudo -u texasnews .venv/bin/python manage.py collectstatic --noinput
sudo -u texasnews .venv/bin/python manage.py createsuperuser
```

`.env` is loaded by `python-dotenv` from the project root; keep it mode `600`.

### 3. gunicorn — `/etc/systemd/system/texas-news.service`

```ini
[Unit]
Description=Texas News Curator (gunicorn)
After=network.target postgresql.service

[Service]
User=texasnews
Group=texasnews
WorkingDirectory=/opt/texas-news/app
ExecStart=/opt/texas-news/app/.venv/bin/gunicorn config.wsgi:application \
    --bind unix:/run/texas-news/gunicorn.sock --workers 2 --timeout 60
RuntimeDirectory=texas-news
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now texas-news
```

### 4. Pipeline timer (replaces cron) — every 3 hours

`/etc/systemd/system/texas-news-pipeline.service`

```ini
[Unit]
Description=Texas News Curator pipeline run

[Service]
Type=oneshot
User=texasnews
WorkingDirectory=/opt/texas-news/app
ExecStart=/opt/texas-news/app/.venv/bin/python manage.py run_pipeline
```

`/etc/systemd/system/texas-news-pipeline.timer`

```ini
[Unit]
Description=Run the Texas News pipeline every 3 hours

[Timer]
OnCalendar=*-*-* 00/3:00:00
RandomizedDelaySec=5m
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
sudo systemctl enable --now texas-news-pipeline.timer
systemctl list-timers texas-news-pipeline.timer
journalctl -u texas-news-pipeline -n 50      # logs of the last runs
```

Plain cron alternative (as the `texasnews` user):

```cron
0 */3 * * * cd /opt/texas-news/app && .venv/bin/python manage.py run_pipeline >> /var/log/texas-news/pipeline.log 2>&1
```

The **Run now** button on the dashboard launches the same `run_pipeline` command as a
detached subprocess, so the web user must be able to write to `media/` and the DB.

### 5. nginx — `/etc/nginx/sites-available/texas-news`

```nginx
server {
    listen 80;
    server_name news.example.com;
    client_max_body_size 5m;

    location /static/ { alias /opt/texas-news/app/staticfiles/; expires 7d; }
    location /media/  { alias /opt/texas-news/app/media/; expires 1d; }

    location / {
        proxy_pass http://unix:/run/texas-news/gunicorn.sock;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/texas-news /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d news.example.com     # TLS
```

`media/` (downloaded story images) is served by nginx in production and by Django
only when `DEBUG=true`. Images are small; prune old ones occasionally with
`find media/stories -mtime +30 -delete` if disk matters.

### 6. Updating

```bash
cd /opt/texas-news/app && sudo -u texasnews git pull
sudo -u texasnews .venv/bin/pip install -r requirements.txt
sudo -u texasnews .venv/bin/python manage.py migrate
sudo -u texasnews .venv/bin/python manage.py collectstatic --noinput
sudo systemctl restart texas-news
```
