# CLAUDE.md — Texas News Curator

## What this project is

A small self-hosted web tool that fetches the latest news from a fixed list of Texas
news RSS feeds, scores each story for importance / trending / audience fit using the
Claude API, and turns the best stories into ready-to-post Facebook content
(title + short description + downloadable image).

The owner opens the dashboard once a day, picks stories, copies the text, downloads
the image, and posts to a Facebook page manually. There is no Facebook posting
integration and none is planned. This is a hobby tool for one user — keep it simple,
boring, and reliable. No auth beyond a single shared password or basic auth.

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
- HTMX is allowed for small interactions (mark as posted, refresh). No other JS
  framework. Vanilla JS for copy-to-clipboard.
- Tailwind via CDN is fine for styling. Do not add a Node build step.
- Scheduling: Django management commands run by cron / systemd timer on the VPS.
  Do not add Celery/Redis.
- Deployment target: single Linux VPS (Hostinger KVM), gunicorn + nginx.
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
│   ├── services/
│   │   ├── feeds.py        # RSS fetch + dedupe
│   │   ├── images.py       # og:image extraction + download
│   │   ├── scoring.py      # Claude scoring pass
│   │   └── generation.py   # Claude post-text generation
│   ├── prompts/            # prompt text files, one per task
│   └── management/commands/
│       ├── fetch_feeds.py
│       ├── score_stories.py
│       ├── generate_content.py
│       └── run_pipeline.py # runs the three above in order
├── media/                  # downloaded images (gitignored)
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
- posted_at, skipped_at

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
5. **run_pipeline** — runs 1–4 in order. Cron every 3 hours.

Idempotent: re-running any step must not create duplicates or re-spend tokens on
already-processed stories.

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
- If no image is found, still show the story with a placeholder and a warning badge.
- Do not add any stock-photo fallback, watermarking, or image editing.

## Dashboard (single page + detail)

- `/` — cards sorted by (importance + shareability) desc, then published_at desc.
  Default filter: status `generated`. Filters: category, source city, status,
  date range. Show cluster_size as a "N sources" badge.
- Each card: image thumbnail, post_title, post_description, source + city + time,
  score badges, buttons: **Copy title**, **Copy description**, **Copy both**,
  **Download image**, **Open article**, **Mark posted**, **Skip**.
- `/story/<id>/` — full detail including score_reason, reel_script, raw feed data.
- `/hidden/` — political / live-sports stories that were auto-hidden, with an
  "unhide" button (owner override).
- `/sources/` — manage sources (Django admin is acceptable for this).
- Header shows last pipeline run time and a **Run now** button that triggers
  `run_pipeline` (via subprocess or a lightweight background thread; must not block
  the request for more than a second).
- Mobile-friendly: the owner may open this on a phone.

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
  JSON parsing of Claude responses (with fixture responses), and og:image extraction
  (with saved HTML fixtures). Do not call the real Claude API in tests.
- Commit after each milestone below.

## Milestones (build in this order)

1. Project skeleton, settings, Postgres, models, admin, seed sources, `fetch_feeds`.
2. Dedupe/cluster + `score_stories` with prompt file + JSON parsing + tests.
3. Image extraction/download + `generate_content`.
4. Dashboard with filters, copy buttons, download, mark posted/skip, hidden view.
5. `run_pipeline`, Run-now button, PipelineRun display, cron instructions in README.
6. Deployment notes: gunicorn, nginx, systemd timer, `.env`, media serving.

## Out of scope (do not build unless asked)

- Posting to Facebook / Meta Graph API
- Video or reel rendering
- User accounts, multi-tenant, roles
- Stock image APIs
- Full-article scraping or archiving
- Analytics
