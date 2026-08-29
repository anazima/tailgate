# CLAUDE.md — Texas News Curator

## What this project is

A small self-hosted web tool that fetches the latest news from a fixed list of Texas
news RSS feeds, scores each story for importance / trending / audience fit using the
Claude API, and turns the best stories into ready-to-post Facebook content
(title + short description + downloadable image).

The owner opens the dashboard once a day, picks stories, copies the text, downloads
the image, and posts to a Facebook page manually. There is no Facebook posting
integration and none is planned. This is a hobby tool for one user — keep it simple,
boring, and reliable. Auth is a single Django user (same login for the dashboard and
`/admin/`); no roles, no multi-tenant.

## Target audience (drives all content decisions)

- Facebook page audience: ~97% US, almost all Texas.
- Top cities: San Antonio, Dallas, Fort Worth, El Paso, Corpus Christi. Rotate coverage
  across all five — this is NOT a Dallas-only page.
- ~74% aged 45+, male-skewed. Tone: calm, clear, plain English, no slang, no memes,
  no Gen-Z humor, no hype.
- Page identity: Texas news + Dallas Cowboys. Cowboys stories are welcome only when
  they have a 24h+ shelf life (analysis, roster news, off-field, nostalgia). Never
  live scores or in-game updates.
- HARD RULE: no politics, no border/immigration, no elections, no candidates, no
  culture-war topics. These must be auto-flagged and hidden by default.
- Good categories: weather & severe storms, wildfires, hurricanes, community &
  human-interest, local business & economy, cost of living, Texas history / nostalgia,
  Cowboys (slow news), high school & college football culture, food & BBQ, Texas pride.

## Stack

- Python 3.12
- Django 5.x (server-rendered HTML templates; no React, no SPA)
- PostgreSQL 16
- `feedparser` for RSS, `requests` + `beautifulsoup4` for image extraction
- `anthropic` official Python SDK for scoring and content generation
- `pywebpush` for browser push notifications (Web Push API + VAPID)
- HTMX is allowed for small interactions (mark as posted, refresh). No other JS
  framework. Vanilla JS for copy-to-clipboard.
- Tailwind via CDN is fine for styling. Do not add a Node build step.
- Scheduling: Django management commands run by a systemd timer on the VPS and a
  `launchd` job locally — top of every hour. Do not add Celery/Redis.
- Dev server port is **8100** (pinned in `manage.py`; reserved in
  `/Users/Shared/claude-ports/registry.json`). Never use 8000.
- Deployment target: shared AWS Ubuntu VPS managed by aaPanel — `https://tailgate.retoph.com`,
  gunicorn on 127.0.0.1:8100 under supervisor as user `www`, nginx rules in `deploy/nginx-rewrite.conf`,
  systemd timer for the pipeline. See README §Deployment; update with `deploy/pull-deploy.sh`.
- Config via environment variables (`python-dotenv` in dev). Never commit secrets.

## Project layout

```
texas-news-curator/
├── CLAUDE.md
├── README.md
├── .env.example
├── requirements.txt
├── manage.py
├── config/                 # Django project (settings, urls, wsgi)
├── news/                   # single Django app
│   ├── models.py
│   ├── admin.py
│   ├── views.py
│   ├── urls.py
│   ├── templates/news/
│   ├── static/news/
│   ├── middleware.py       # login-required gate for the whole dashboard
│   ├── services/
│   │   ├── feeds.py        # RSS fetch + dedupe
│   │   ├── images.py       # og:image extraction + download
│   │   ├── claude.py       # API client, prompt loading, defensive JSON parsing
│   │   ├── scoring.py      # Claude scoring pass
│   │   ├── generation.py   # Claude post-text generation
│   │   ├── push.py         # browser push: notify() + notify_top_stories()
│   │   └── cleanup.py      # 30-day retention purge
│   ├── prompts/            # prompt text files, one per task
│   └── management/commands/
│       ├── fetch_feeds.py
│       ├── score_stories.py
│       ├── generate_content.py
│       ├── run_pipeline.py # fetch → cluster → score → generate → notify → cleanup
│       ├── cleanup_old.py
│       └── generate_vapid_keys.py
├── deploy/                 # gunicorn/supervisor/nginx/systemd configs + pull-deploy.sh
├── media/                  # downloaded images (gitignored)
├── logs/                   # local launchd pipeline log (gitignored)
└── tests/
```

## Data model

**Source**
- name, feed_url, homepage_url, city (enum: san_antonio, dallas, fort_worth, el_paso,
  corpus_christi, statewide, other), is_active, last_fetched_at, last_error

**Story**
- source (FK), url (unique), title, summary (from feed, may be empty), published_at,
  fetched_at
- image_url, image_file (local path under media/), image_width, image_height
- cluster_key (see dedupe) and cluster_size (how many sources carry this story)
- status enum: `new` → `scored` → `generated` → `posted` | `skipped` | `hidden`
- Scoring fields (nullable until scored): importance (1–10), shareability (1–10),
  category (enum matching the good categories above + `politics` + `sports_live` +
  `other`), is_political (bool), is_cowboys (bool), score_reason (short text),
  scored_at
- Generated fields (nullable until generated): post_title, post_description,
  reel_script (optional, for a separate reel workflow), generated_at
- posted_at, skipped_at, notified_at (push sent once per story)

**PushSubscription**
- endpoint (unique), p256dh, auth, user_agent, created_at, last_error — one row per
  browser that opted in. Dead endpoints (404/410) are deleted automatically.

**PipelineRun** (for visibility on the dashboard)
- started_at, finished_at, command, stories_fetched, stories_scored,
  stories_generated, error

## Pipeline

1. **fetch_feeds** — for each active Source: parse RSS, create Story rows for unseen
   URLs (normalize URLs: strip tracking params, trailing slashes). Skip anything older
   than 72 hours. Record errors per source, never let one bad feed abort the run.
2. **dedupe / cluster** — after fetching, compute `cluster_key` by normalizing the
   title (lowercase, strip punctuation/stopwords) and grouping by fuzzy similarity
   (rapidfuzz, threshold ~85). `cluster_size` = number of distinct sources in the
   cluster. This is the trending signal — free, no external API.
3. **score_stories** — batch all `new` stories (up to ~40 per request) to Claude.
   Send only headline + feed summary + source + published time + cluster_size.
   Ask for JSON: importance, shareability, category, is_political, is_cowboys,
   reason. Set `is_political=true` stories to status `hidden`. Set live sports /
   match-result stories to `hidden`. Everything else → `scored`.
4. **generate_content** — for stories with status `scored` and
   `(importance + shareability) >= threshold` (default 12, env-configurable), fetch
   the article page, extract the main image, download it to media/, then ask Claude
   for post_title and post_description. → `generated`.
5. **notify** — push a browser notification for each newly generated story with an
   image and `importance + shareability >= PUSH_SCORE_THRESHOLD` (default 18).
   Each story is notified once (`notified_at`); 6+ at once collapse into one summary.
6. **cleanup** — delete stories (all statuses), their image files, orphaned files in
   `media/stories/`, and PipelineRun rows older than `RETENTION_DAYS` (default 30).
7. **run_pipeline** — runs 1–6 in order, every hour at :00. Skips itself if another
   run is still in progress (a run unfinished after 45 min counts as crashed). Each
   step's failure is recorded on the PipelineRun but does not stop the next step.

Idempotent: re-running any step must not create duplicates or re-spend tokens on
already-processed stories. A missing `ANTHROPIC_API_KEY` must surface as a run error,
never as a silent "0 scored".

## Claude API usage

- Use the `anthropic` SDK. API key from `ANTHROPIC_API_KEY` env var.
- Model IDs live in env vars with sane defaults so they can be swapped without code
  changes: `SCORING_MODEL` (default a Haiku-class model) and `GENERATION_MODEL`
  (default a Sonnet-class model). Before hardcoding a default, check the current
  model list at https://docs.claude.com/en/docs/about-claude/models/overview.
- Always request JSON output and parse defensively (strip code fences, validate
  fields, fall back gracefully). Log raw responses on parse failure.
- Prompts live as plain text files in `news/prompts/` and are loaded at runtime —
  never inline long prompts in Python.
- Use the audience section of this file verbatim as the system prompt context for
  both scoring and generation.
- Keep token spend tiny: scoring in batches, generation only above threshold,
  never send full article bodies (headline + summary + first ~500 chars max).

### Scoring prompt requirements
- Output strict JSON array, one object per input story id.
- Explicitly penalize: political/partisan topics, border/immigration, elections,
  live game scores, crime that is purely sensational, national stories with no
  Texas angle.
- Reward: statewide impact, weather/safety, human-interest, nostalgia, stories that
  a 55-year-old Texan would share with family, stories carried by multiple sources.

### Generation prompt requirements
- `post_title`: max 90 characters, plain, no clickbait, no emojis, no ALL CAPS.
- `post_description`: 2–3 sentences, max ~300 characters, written in our own words
  (never copy sentences from the article), neutral reporting tone, ends with the
  source name in the form "via Texas Tribune".
- Optional `reel_script`: ~90–110 words, calm narration, only when
  `GENERATE_REEL_SCRIPT=true`.

## Image handling

- Fetch the article HTML with a normal browser User-Agent and a 10s timeout.
- Priority: `og:image` → `twitter:image` → largest `<img>` in the article body.
- Download to `media/stories/<story_id>.<ext>`, record width/height with Pillow.
- Dashboard shows the image full-size in a lightbox and offers a direct download
  link (`Content-Disposition: attachment`). Also show the original image URL.
- If no image is found the story is still generated, but the dashboard hides it by
  default (Images filter: "With image" / "All"). Push notifications require an image.
- KXAN / KTSM (Nexstar) return 403 to article fetches, so their stories rarely have
  images.
- Do not add any stock-photo fallback, watermarking, or image editing.

## Dashboard (single page + detail)

- `/` — cards sorted by (importance + shareability) desc, then published_at desc.
  Default filters: status `generated`, images `with`. Filters: category, source
  city, status, images, date range. Show cluster_size as a "N sources" badge.
- Each card: image thumbnail, post_title, post_description, source + city + time,
  a single **total score badge** (e.g. `18/20`; breakdown on hover and on the detail
  page), buttons: **Copy title**, **Copy description**, **Copy both**,
  **Download image**, **Open article**, **Mark posted**, **Skip**.
- `/story/<id>/` — full detail including score_reason, reel_script, raw feed data.
- `/hidden/` — political / live-sports stories that were auto-hidden, with an
  "unhide" button (owner override).
- `/sources/` — manage sources (Django admin is acceptable for this).
- Header is a single compact bar on every screen size: last-run status (with error
  flag) on the left, **Run now** + a round burger button on the right. The burger
  opens a dropdown: Dashboard, Hidden, Sources, Admin, Enable/Disable notifications,
  Send test notification, Log out. No page title.
- **Run now** spawns `run_pipeline` as a detached subprocess and must not block the
  request; the header polls `/pipeline-status/` every 8 s while a run is active.
- Mobile-friendly: the owner may open this on a phone. Filters collapse behind a
  "Filters" toggle below `sm`.
- `/login/` — username + password (Django auth). Everything except `/login/`,
  `/admin/`, `/static/`, `/media/` requires login (middleware).
- Favicon / touch icon / web manifest use the red "TN" app icon in `news/static/news/`.

## Browser push notifications

- Standard Web Push (service worker at `/sw.js`, served from the site root by a view).
  VAPID keys in env (`VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_CLAIMS_EMAIL`);
  `python manage.py generate_vapid_keys` prints a fresh pair.
- `news.services.push.notify(title, body, url, tag)` sends to every subscription and
  never raises. `notify_top_stories()` is the pipeline step described above.
- Endpoints: `POST /push/subscribe/`, `POST /push/unsubscribe/`, `POST /push/test/`.
  The test button first shows a *local* notification from the browser, then a real
  server push, so OS-permission problems can be told apart from delivery problems.
- Needs HTTPS in production (localhost exempt). iPhone: only after Add to Home Screen.

## Sources (seed data)

Seed these via a data migration or fixture; the owner will adjust in admin.
Verify each feed URL actually parses before committing the fixture.

- Texas Tribune (statewide)
- Dallas Morning News (dallas)
- Fort Worth Star-Telegram (fort_worth)
- WFAA (dallas)
- KSAT (san_antonio)
- San Antonio Express-News (san_antonio)
- KXAN (statewide/Austin)
- KRIS / Caller-Times (corpus_christi)
- KTSM / El Paso Times (el_paso)
- National Weather Service Texas alerts (statewide)
- Dallas Cowboys official site news (dallas, is_cowboys hint)

## Conventions

- Type hints everywhere. `ruff` for lint/format. Keep functions small.
- Services in `news/services/` are plain functions; views and commands call them.
- Every management command prints a one-line summary and writes a PipelineRun row.
- Log with the standard `logging` module; no print() outside commands.
- Tests: `pytest` + `pytest-django`. Cover URL normalization, dedupe clustering,
  JSON parsing of Claude responses (with fixture responses), og:image extraction
  (with saved HTML fixtures), views, push, and cleanup. Do not call the real Claude
  API or the real push service in tests.
- `tests/conftest.py` has autouse fixtures that point `MEDIA_ROOT` at a temp dir and
  log the test client in. **Never remove the MEDIA_ROOT isolation** — a test once
  ran the cleanup step against the real `media/` folder and deleted every image.
- Prompt files are substituted with `str.replace` on `{story_json}` / `{reel_field}`,
  not `str.format`, so prompt text may contain literal braces.
- Commit after each milestone or feature; run `pytest` and `ruff` before committing.

## Status

All original milestones are built and committed (skeleton, feeds, clustering,
scoring, images, generation, dashboard, run_pipeline / Run now, deployment notes),
plus: Django-user login, hourly schedule (launchd locally, systemd on the VPS),
30-day retention, browser push for 18+ stories, TN favicon/manifest.

Not yet done:
- Dallas Morning News / WFAA / Star-Telegram produce no generated stories so far —
  check their feeds' `last_error` in admin.
- ~8 generated descriptions run slightly over 300 chars; no hard trim yet.

## Runtime settings (env, see `.env.example`)

`SCORING_MODEL`, `GENERATION_MODEL`, `GENERATION_THRESHOLD` (12), `GENERATE_REEL_SCRIPT`,
`PUSH_SCORE_THRESHOLD` (18), `RETENTION_DAYS` (30), `VAPID_*`, `DB_ENGINE`
(`sqlite` dev / `postgres` VPS), `ANTHROPIC_API_KEY`.

## Out of scope (do not build unless asked)

- Posting to Facebook / Meta Graph API
- Video or reel rendering
- User accounts, multi-tenant, roles
- Stock image APIs
- Full-article scraping or archiving
- Analytics
