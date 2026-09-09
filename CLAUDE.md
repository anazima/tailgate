# CLAUDE.md — Texas News Curator

## What this project is

A small self-hosted web tool that fetches the latest news from a fixed list of Texas
news RSS feeds, ranks each story for importance / audience fit using the
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
- Page identity: Texas news + Dallas Cowboys. Cowboys stories are treated exactly like
  any other category — no special restrictions. Live game news, breaking news, scores,
  injuries and in-game developments are all welcome alongside analysis, roster news,
  off-field stories and nostalgia. The page posts Cowboys news as it happens.
- HARD RULE: no politics, no border/immigration, no elections, no candidates, no
  culture-war topics. These must be auto-flagged and hidden by default.
- Good categories: weather & severe storms, wildfires, hurricanes, community &
  human-interest, local business & economy, cost of living, Texas history / nostalgia,
  Cowboys (including live and breaking), high school & college football culture,
  food & BBQ, Texas pride.

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
│   │   ├── triage.py       # stage 1: headline keep/discard
│   │   ├── article.py      # article fetch + trafilatura extraction, 500-word cap
│   │   ├── analysis.py     # stage 2: six-dimension deep read + rollup
│   │   ├── ranking.py      # stage 3: relative ranking
│   │   ├── generation.py   # Claude post-text generation
│   │   ├── push.py         # browser push: notify() + notify_top_stories()
│   │   └── cleanup.py      # 30-day retention purge
│   ├── prompts/            # prompt text files, one per task
│   └── management/commands/
│       ├── fetch_feeds.py
│       ├── score_stories.py  # triage + deep read
│       ├── generate_content.py
│       ├── run_pipeline.py # fetch → cluster → triage → deep read → rank → generate → notify → cleanup
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
- status enum: `new` → `triaged` → `scored` → `generated` → `posted` | `skipped` | `hidden`
- Triage fields (stage 1, headline only): triage_score (1–5), triage_reason, triaged_at,
  category (enum matching the good categories above + `politics` + `sports_live` +
  `other`), is_political (bool), is_cowboys (bool)
- Deep-read fields (stage 2, from the article): six dimensions each 1–5 — scale,
  consequence, proximity, share_trigger, shelf_life, novelty — plus dimension_notes
  (JSON, one justification per dimension quoting the article), key_facts (JSON list of
  3–5 facts), read_confidence (`full` / `partial` / `headline_only`), article_words,
  score_reason, analysed_at, scored_at
- **There is no numeric score.** The six dimensions feed the ranking pass, and
  `daily_rank` is the only thing that gates anything. The ranker sees `hours_old`, so
  breaking news is not penalised for its short `shelf_life` — a short shelf life is a
  reason to post now, not a reason to rank down. There is deliberately no second,
  absolute scale competing with it.
- Ranking + feedback: daily_rank, ranked_at, performance (`well` / `poorly`), performance_at
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
   cluster. **This is NOT an importance signal** — it measures wire-service pickup, so an
   AP story appears everywhere while a real single-source scoop looks like nothing. It is
   passed to the prompts as context only, and used by triage to spot duplicates.
3. **triage** (stage 1, Haiku) — batch all `new` stories (up to 40 per request).
   Headline + feed summary only. Its job is to DISCARD, not to rank: politics, live
   sports, national stories with no Texas angle, purely sensational crime, and obvious
   duplicate coverage of the same event. Discards → `hidden` (with triage_reason, so
   `/hidden/` explains itself); keeps → `triaged`. Owns category, is_political,
   is_cowboys.
3b. **deep read** (stage 2, Sonnet) — for `triaged` stories, fetch the article, extract
   clean text with trafilatura, cut to `ARTICLE_MAX_WORDS` (500) and score the six
   dimensions with a justification each plus 3–5 key_facts. read_confidence is derived
   in code from the extracted word count, never asked of the model. → `scored`.
   Bounded by DEEP_READ_MAX_PER_RUN and
   DEEP_READ_MAX_AGE_HOURS so an unusual news day cannot run away and a story whose
   fetch keeps failing is not retried hourly for 30 days.
3c. **rank** (stage 3, Haiku) — order the deep-read stories of the last
   RANK_WINDOW_HOURS against each other, writing daily_rank. This is the **only**
   judgment the system makes: models calibrate badly in absolute terms, so a fixed
   threshold gives nothing on a quiet day and a flood on a busy one. Ranks are cleared
   wherever they are no longer valid — each pass renumbers from 1, so a leftover number
   would collide with a fresh one. Posted and skipped stories are excluded so the board
   stops moving once the owner has acted, keeping their rank as a record.
4. **generate_content** — for `scored` stories ranked in the top `GENERATION_TOP_N`
   (default 10) with a fresh rank, fetch the article page, extract the main image,
   download it to media/, then ask Claude for post_title and post_description.
   → `generated`.
5. **cleanup** — delete stories (all statuses), their image files, orphaned files in
   `media/stories/`, and PipelineRun rows older than `RETENTION_DAYS` (default 30).
6. **run_pipeline** — runs all of the above in order, every hour at :00. Skips itself if another
   run is still in progress (a run unfinished after 45 min counts as crashed). Each
   step's failure is recorded on the PipelineRun but does not stop the next step.

Idempotent: re-running any step must not create duplicates or re-spend tokens on
already-processed stories. A missing `ANTHROPIC_API_KEY` must surface as a run error,
never as a silent "0 scored".

## Claude API usage

- Use the `anthropic` SDK. API key from `ANTHROPIC_API_KEY` env var.
- Model IDs live in env vars with sane defaults so they can be swapped without code
  changes: `TRIAGE_MODEL` (default a Haiku-class model, also used for ranking),
  `DEEP_READ_MODEL` and `GENERATION_MODEL` (both default a Sonnet-class model). Before hardcoding a default, check the current
  model list at https://docs.claude.com/en/docs/about-claude/models/overview.
- Always request JSON output and parse defensively (strip code fences, validate
  fields, fall back gracefully). Log raw responses on parse failure.
- Prompts live as plain text files in `news/prompts/` and are loaded at runtime —
  never inline long prompts in Python.
- Use the audience section of this file verbatim as the system prompt context for
  both scoring and generation.
- Keep token spend tiny: triage in batches of 40 on the cheap model, deep read only on
  triage survivors and capped per run, generation only above threshold.
- **Never send full article bodies.** The deep read sends at most `ARTICLE_MAX_WORDS`
  (500 words) of extracted text — news is inverted-pyramid, so the first 500 words carry
  the substance. Everything else sends headline + summary only.
- **Article text is never stored.** What persists is key_facts, the justifications and a
  word count. This is what keeps "no full-article archiving" true.

### Triage prompt requirements (stage 1)
- Output strict JSON array, one object per input story id: keep, triage_score (1–5),
  category, is_political, is_cowboys, reason.
- Discard: political/partisan topics, border/immigration, elections, candidates,
  culture-war, live game scores **for teams other than the Cowboys**, purely sensational
  crime, national stories with no Texas angle, and duplicate coverage of an event already
  kept. Cowboys live/breaking news is explicitly kept and categorised `cowboys`.
- `cluster_size` is passed as context only, and the prompt says so explicitly: it
  measures wire-service pickup, not importance, and must not be scored on.
- Borderline stories survive to stage 2. Triage is a filter, not an editor.

### Deep-read prompt requirements (stage 2)
- Six dimensions, each 1–5 against anchors written into the prompt — never an
  unanchored scale. Each needs a justification quoting the article.
- Reward: statewide impact, weather/safety, human-interest, nostalgia, cost of living,
  stories a 55-year-old Texan would share with family.
- read_confidence is stated to the model as a measured fact, not requested from it.

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

- `/` — cards sorted by daily_rank (best first), then published_at desc.
  Default filters: status **"To post + posted"** (`current` — generated plus posted, so
  the owner can see what is done and what is not; skipped and hidden stay out),
  category **Cowboys**, images `with`, sort `rank`. Filters: category, source city,
  status, images, date range. Show cluster_size as a "N sources" badge.
- Each card: image thumbnail, post_title, post_description, source + city + time,
  a **rank badge** (`#1`; the six dimensions on hover, in full on the detail page),
  a `Headline only` chip when the site blocked the fetch, a green **Posted** badge once
  posted, buttons: **Copy title**, **Copy description**, **Copy both**,
  **Download image**, **Open article**, **Mark posted**, **Skip**, and after posting
  **Did well** / **Did poorly**.
- Marking posted **re-renders the card in place** rather than removing it. Skip and
  unhide do remove it — those mean "not this one".
- `/story/<id>/` — full detail: the six dimensions with their quoted justifications,
  key_facts, read confidence, rank, score_reason, reel_script, raw feed data.
- `/hidden/` — stories triage discarded (politics, non-Cowboys live sports, no Texas
  angle, sensational crime, duplicates), each showing why, with an "unhide" button
  (owner override). Unhide returns a story to `triaged` so stage 2 reads it properly.
- `/sources/` — manage sources (Django admin is acceptable for this).
- Header is a single compact bar on every screen size: last-run status (with error
  flag) on the left, **Run now** + a round burger button on the right. The burger
  opens a dropdown: Dashboard, Hidden, Sources, Admin, Enable/Disable notifications,
  Send test notification, Log out. No page title. (The pipeline sends no notifications
  of its own; the menu items drive the manual test path only.)
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
- Blogging The Boys (dallas, is_cowboys) — highest rate, ~9/day; feed holds only 10 items
- The Landry Hat (dallas, is_cowboys) — ~5.4/day
- Inside The Star (dallas, is_cowboys) — ~2.4/day
- Pro Football Rumors (other) — NFL-wide, ~1 story in 15 is Cowboys, but breaking
  transactions land there first; the no-Texas-angle rule bins the rest

Rejected after measuring publish rate (not entry count) on 2026-09-09: Google News and
Reddit r/cowboys both return links our fetcher reads as 0 words; Sport DFW looked large
at 90 entries but publishes 0.1/day; ESPN, NFL.com, Yahoo, CBS, 247Sports, SI, Bleacher
Report, Cowboys Wire and a dozen others return no entries at all. There is no faster
Cowboys-only RSS feed than the four above — real-time Cowboys news lives on X, not RSS.

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

The single-stage scorer was replaced by the three-stage cascade described under
Pipeline: triage → deep read → rank. The numeric score was then removed entirely at the
owner's request — one system, not two. Stories scored before the change have no
dimensions and no rank, so they render without a badge and never generate; the 30-day
purge clears them on its own. There is deliberately no backfill.

Automatic push notifications were removed with the score that gated them. The push
plumbing (service worker, VAPID, subscribe endpoints, `notify()`, the test button) is
intact and unused by the pipeline — the dashboard is the whole interface now.

Not yet done:
- The 1–5 anchors and `GENERATION_TOP_N` are set by reasoning, not by observed results.
  Watch the first few days: if too many or too few stories get written up each day,
  GENERATION_TOP_N is the dial.
- No worked examples in the deep-read prompt yet. Once ~30–50 stories carry a
  `performance` verdict, feeding the best and worst back into the prompt is what turns
  this from Claude's generic opinion into a ranker tuned to this page.
- Dallas Morning News / WFAA / Star-Telegram produce no generated stories so far —
  check their feeds' `last_error` in admin.
- ~8 generated descriptions run slightly over 300 chars; no hard trim yet.

## Runtime settings (env, see `.env.example`)

`SCORING_MODEL` / `TRIAGE_MODEL`, `DEEP_READ_MODEL`, `GENERATION_MODEL`,
`ARTICLE_MAX_WORDS` (500), `ARTICLE_FETCH_WORKERS` (8), `DEEP_READ_BATCH_SIZE` (6),
`DEEP_READ_MAX_PER_RUN` (15), `DEEP_READ_MAX_AGE_HOURS` (48), `RANK_WINDOW_HOURS` (24),
`GENERATION_TOP_N` (10), `GENERATE_REEL_SCRIPT`,
`RETENTION_DAYS` (30), `VAPID_*`, `DB_ENGINE`
(`sqlite` dev / `postgres` VPS), `ANTHROPIC_API_KEY`.

## Out of scope (do not build unless asked)

- Posting to Facebook / Meta Graph API
- Video or reel rendering
- User accounts, multi-tenant, roles
- Stock image APIs
- Full-article archiving. The deep read fetches an article, sends at most 500 words to
  Claude and keeps only the extracted facts — the body is never written to the database.
- Analytics
