# AGENTS.md

This file is the canonical guide for coding agents working in this repository.

## Project Overview

`rss-de-valor` is a personal RSS aggregator for Brazilian newspaper columnists
and climate-risk sources. It scrapes or consumes configured sources, generates
individual RSS feeds, preserves per-source history, and builds OPML.

The canonical production delivery is private:

- Cloudflare Worker at `https://feeds.paulofehlauer.com`;
- HTTP Basic Auth over HTTPS;
- private R2 Standard bucket;
- immutable snapshots selected by `current.json`;
- GitHub Actions publication every six hours.

The public GitHub Pages workflow, `feeds/`, and `history/` are still present as
a temporary contingency. They may only be removed at the explicit public-cut
gate. The `clima` group also feeds an automated climate-risk digest.

Current inventory as of 2026-07-27: 108 configured sources, 106 generated
feeds, two direct `ExistingRssScraper` sources, 213 internal snapshot objects,
and 107 authenticated private routes.

## Safety and Authorization Gates

- Preserve pre-existing working-tree changes and avoid unrelated files.
- Do not commit or push unless the user explicitly authorizes it.
- Do not disable GitHub Pages, stop the public workflow, remove `feeds/` or
  `history/`, or rewrite Git history without a separate explicit authorization.
- Do not change DNS, Worker routes, R2 access, secrets, or external
  infrastructure unless the task explicitly includes that operation.
- Never request secrets in chat or print them in commands, logs, XML, OPML, or
  URLs.
- Treat Feedbin subscription exports as secret-bearing until sanitized; its
  `subscriptions.xml` may embed Basic credentials in `xmlUrl`.
- Keep `paulofehlauer.com` redirecting to Linktree. Do not alter `fehla.xyz`.
- `workers.dev` and Worker Preview URLs must remain disabled in production.

## Commands

Use the repository virtual environment, never system Python:

```bash
# Runtime dependencies and feed generation
.venv/bin/pip install -r requirements.txt
.venv/bin/python3 main.py

# Private-publication dependencies and Python tests
.venv/bin/pip install -r requirements-private.txt
.venv/bin/python3 -m unittest discover -s tests -v

# Worker validation
cd worker
npm ci
npm run check
npm test
npm run deploy -- --dry-run
```

The Wrangler command above is a dry run. A real deploy requires an explicit
external-infrastructure authorization.

## Architecture

The private pipeline is:

```text
hydrate active R2 snapshot
  → main.py
  → validate/stage allowlisted objects
  → upload immutable snapshot
  → verify remote objects and re-read pointer
  → conditionally replace current.json
  → run authenticated and anonymous canaries
  → retain 28 snapshots
```

**`main.py`** orchestrates collection, history comparison, feed generation,
self-link normalization, OPML generation, and the legacy HTML index.

**`src/scrapers.py`** contains scraper classes. Most inherit `BaseScraper` and
implement `_extract_article_data()` or `get_articles()`. `ExistingRssScraper`
and `PaulGrahamScraper` have special behavior. New classes must be registered in
`get_scraper_class()`.

**`src/utils.py`** handles feed, OPML, HTML, config, and history utilities.
`FEED_BASE_URL` controls generated self-links. It must be a credential-free
HTTPS origin. Production uses `https://feeds.paulofehlauer.com`; an unset local
value preserves the legacy Pages origin. The `group_display_names` map is
duplicated in `generate_opml()` and `generate_html_index()`.

**`config/sources_config.json`** is the source of truth for sources. Each source
has `name`, `url`, `scraper`, `feed_file`, `history_file`, and `group`.

**`config/private_publication_allowlist.json`** defines publication policy. It
includes configured generated sources, excludes `ExistingRssScraper`, publishes
the private OPML, rejects aggregate feeds, and disables the private HTML index.

**`scripts/`** implements hydration, manifest construction, validation,
publication, rollback, and the explicitly gated LinkedIn baseline repair. R2
operations use its S3-compatible API.

**`worker/`** contains the TypeScript Worker. Authentication happens before
method/path resolution. The Worker serves only manifest routes from the active
snapshot, with private cache headers, ETag, `Last-Modified`, `HEAD`, and `304`.

**`.github/workflows/private-feed-publication.yml`** is the active full private
publisher. It uses `contents: read`, canonical `FEED_BASE_URL`, and the shared
`private-feed-r2-publication` concurrency group. Its
`repair_linkedin_baseline` input is manual-only and carries exactly the fixed
12-source repair allowlist across hydration; it is not a generic bootstrap.
Its named validator profile may correct a synthetic publication date only
when the same allowlisted item moves from both fallback author and short
content to a known author and complete content.

**`.github/workflows/private-feed-pilot.yml`** is retained for controlled
diagnostics but its repository-level gate normally remains `false`.

**`.github/workflows/private-feed-rollback.yml`** performs a validated,
full-snapshot pointer rollback and shares the publication concurrency group.

**`.github/workflows/workflow.yml`** is the legacy public publisher. It still
commits `feeds/` and `history/` with `[skip ci]` and must remain until the
separate cut gate.

## Adding a Source

1. Add the source to `config/sources_config.json`.
2. If it needs scraping, implement and register a scraper in
   `src/scrapers.py`.
3. Use `ExistingRssScraper` only for native upstream RSS; these feeds remain
   direct and are not copied into R2.
4. Add new group display names in both maps in `src/utils.py`.
5. Run Python tests and local generation.
6. Verify that the derived private inventory contains only the intended feed
   and history paths.

Do not publish by globbing `feeds/*.xml`. Aggregate or orphaned files require an
explicit policy change.

## Removing a Source

1. Remove the config entry.
2. Remove its generated feed/history only when included in the approved change.
3. Verify the derived allowlist and snapshot tests.
4. Confirm that hydration ignores only legacy extras and still fails on a
   missing or divergent required object.

The YouTube transcription source was removed from active configuration. The
`YouTubeTranscriptScraper` class and dependency remain as inactive legacy code;
do not re-add a YouTube feed without a new decision.

## Key Conventions

- Dates are timezone-aware (`pytz`), normally São Paulo for Brazilian sources
  and UTC for international sources.
- HTTP requests use `requests_retry_session()` with retries and a 30-second
  timeout.
- Preserve existing feed content on transient scraper/enrichment failures.
  `main.py` applies anti-downgrade merging to LinkedIn newsletters, Folha
  full-content RSS, and Valor/O Globo.
- Normalize self-links after every scraper run, including preserved feeds.
- Existing RSS sources must keep upstream URLs in OPML.
- A publication must validate every object before activation; partial
  activation is forbidden.
- Publication and rollback must share one serialized concurrency group.
- A failed pre-activation run must leave `current.json` unchanged. Failed
  post-activation canaries must restore the previous pointer.
- The R2 bucket must have no `r2.dev`, bucket Custom Domain, or anonymous
  policy.
- Private workflow actions are pinned by full commit SHA.
- `.venv` is local and must never be committed.

## Documentation

- `README.md` — public project overview and local setup
- `docs/private-feed-publication-cloudflare-spec.md` — architecture, contracts,
  security, tests, and migration record
- `docs/private-feed-publication-runbook.md` — operations, rollback, rotation,
  and incident recovery
- `BACKLOG.md` — current gates and deferred work
