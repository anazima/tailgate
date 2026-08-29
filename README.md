# Texas News Curator

Self-hosted tool that pulls Texas news RSS feeds, scores stories with Claude for a
Texas / Dallas Cowboys Facebook page, and turns the best ones into ready-to-post
title + description + image. The owner opens the dashboard, copies the text,
downloads the image, and posts manually. See `CLAUDE.md` for the full spec.

## Local development

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # fill in ANTHROPIC_API_KEY
python manage.py migrate        # SQLite by default; seeds the 11 Texas sources
python manage.py runserver      # http://127.0.0.1:8100  (port pinned in manage.py)
python manage.py createsuperuser   # login for the dashboard and /admin/
```

Run the pipeline by hand:

```bash
python manage.py fetch_feeds        # RSS → Story rows + clustering
python manage.py score_stories      # Claude scoring (Haiku), hides politics / live sports
python manage.py generate_content   # image + post text (Sonnet) for stories ≥ threshold
python manage.py run_pipeline       # all of the above, in order, then purge old data
python manage.py cleanup_old        # just the purge (stories/images/runs older than RETENTION_DAYS)
```

Tests and lint:

```bash
pytest
ruff check . && ruff format --check .
```

## Browser push notifications

The dashboard can send push notifications to any browser that opts in (menu →
**Enable notifications**; **Send test notification** confirms delivery). Setup:

1. `python manage.py generate_vapid_keys` and paste the two lines into `.env`, plus
   `VAPID_CLAIMS_EMAIL`.
2. Push requires HTTPS in production (localhost is exempt for development).
3. iPhone/iPad: Safari only allows push for sites added to the Home Screen
   (Share → Add to Home Screen), then enable notifications from inside that app.

Each pipeline run pushes one notification per newly generated story scoring
`PUSH_SCORE_THRESHOLD` or higher (default 18/20; only stories with an image, each
story once). Six or more at once collapse into a single summary notification.
`news.services.push.notify(title, body, url)` sends anything else you need.

## Environment variables

| Variable | Default | Notes |
|---|---|---|
| `SECRET_KEY` | — | required in production |
| `DEBUG` | `true` | set `false` on the VPS |
| `ALLOWED_HOSTS` | `127.0.0.1,localhost` | comma-separated |
| `DB_ENGINE` | `sqlite` | `postgres` on the VPS |
| `POSTGRES_DB/USER/PASSWORD/HOST/PORT` | — | used when `DB_ENGINE=postgres` |
| `ANTHROPIC_API_KEY` | — | required for scoring/generation |
| `SCORING_MODEL` | `claude-haiku-4-5` | Haiku-class |
| `GENERATION_MODEL` | `claude-sonnet-5` | Sonnet-class |
| `GENERATION_THRESHOLD` | `12` | importance + shareability needed to generate |
| `GENERATE_REEL_SCRIPT` | `false` | also produce a ~100-word reel narration |
| `VAPID_PUBLIC_KEY` / `VAPID_PRIVATE_KEY` | empty | browser push keys; `python manage.py generate_vapid_keys` |
| `VAPID_CLAIMS_EMAIL` | — | contact email sent with each push (required by push services) |
| `PUSH_SCORE_THRESHOLD` | `18` | push a notification for new stories scoring at least this |
| `RETENTION_DAYS` | `30` | stories, images and run logs older than this are deleted at the end of each pipeline run |

## Deployment — tailgate.retoph.com (AWS Ubuntu 24.04, aaPanel)

The production box is shared with other sites and managed by aaPanel; nginx, PostgreSQL 16
and supervisor already exist there. Everything below is checked in under `deploy/`.

| Piece | Where |
|---|---|
| App checkout | `/www/wwwroot/tailgate` (git clone of `main`, owner `ubuntu:www`) |
| Virtualenv | `/www/wwwroot/tailgate/venv` |
| Secrets | `/www/wwwroot/tailgate/.env` (mode 640) |
| gunicorn | supervisor program `tailgate`, user `www`, `127.0.0.1:8100` — `deploy/gunicorn.conf.py`, `deploy/supervisor-tailgate.conf` |
| nginx | aaPanel vhost for the domain + `deploy/nginx-rewrite.conf` installed as `/www/server/panel/vhost/rewrite/tailgate.retoph.com.conf` (static/media from disk, everything else proxied) |
| TLS | Let's Encrypt via aaPanel (auto-renews); Cloudflare in front |
| Pipeline | `deploy/tailgate-pipeline.service` + `.timer` — top of every hour (Asia/Qatar), runs as `www` |
| Logs | `/www/wwwroot/tailgate/logs/` (gunicorn + supervisor), `journalctl -u tailgate-pipeline` |

### Update after a push to `main`

```bash
ssh aws-web /www/wwwroot/tailgate/deploy/pull-deploy.sh
```

Pulls, installs requirements, migrates, collects static, fixes permissions, restarts
gunicorn and smoke-tests `/login/`.

### First-time setup (already done; kept for reference)

```bash
sudo -u postgres psql -c "CREATE ROLE tailgate LOGIN PASSWORD '...';"
sudo -u postgres psql -c "CREATE DATABASE tailgate OWNER tailgate;"
git clone https://github.com/anazima/tailgate.git /www/wwwroot/tailgate
cd /www/wwwroot/tailgate && python3.12 -m venv venv && venv/bin/pip install -r requirements.txt
mkdir -p logs media staticfiles && cp .env.example .env   # fill in; DEBUG=false, DB_ENGINE=postgres
venv/bin/python manage.py migrate && venv/bin/python manage.py collectstatic --noinput
sudo cp deploy/supervisor-tailgate.conf /etc/supervisor/conf.d/tailgate.conf
sudo supervisorctl reread && sudo supervisorctl update
sudo cp deploy/nginx-rewrite.conf /www/server/panel/vhost/rewrite/tailgate.retoph.com.conf
sudo /www/server/nginx/sbin/nginx -t && sudo /www/server/nginx/sbin/nginx -s reload
sudo cp deploy/tailgate-pipeline.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now tailgate-pipeline.timer
```

Useful checks: `sudo supervisorctl status tailgate`, `systemctl list-timers tailgate-pipeline.timer`,
`sudo journalctl -u tailgate-pipeline -n 50`.

```
