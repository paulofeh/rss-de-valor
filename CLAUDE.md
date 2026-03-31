# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

RSS feed aggregator for Brazilian newspaper columnists. Scrapes columnist pages (or consumes existing RSS feeds), generates individual and grouped RSS feeds, OPML, and an HTML index page. Runs automatically every 6 hours via GitHub Actions and publishes to GitHub Pages.

## Commands

```bash
# Run the scraper (generates all feeds, OPML, and HTML)
.venv/bin/python3 main.py

# Install dependencies (use local venv, never system Python)
.venv/bin/pip install -r requirements.txt
```

There are no tests or linters configured.

## Architecture

The pipeline flows: `main.py` → scrapers → feed/OPML/HTML generation → `feeds/` output.

**`main.py`** — Orchestrates everything: loads config, instantiates scrapers, checks history for new articles, generates individual feeds, grouped feeds (by newspaper/vehicle), OPML, and HTML index.

**`src/scrapers.py`** — All scraper classes inherit from `BaseScraper`. Each overrides `_extract_article_data(soup)` and returns a dict with keys: `title`, `link`, `pubdate`, `author`, `description`. Exception: `ExistingRssScraper` and `PaulGrahamScraper` override `get_latest_article()` directly. New scrapers must be registered in the `get_scraper_class()` dict at the bottom of the file.

**`src/utils.py`** — Feed generation (`CustomRssFeed` extending `Rss201rev2Feed`), OPML/HTML generation, history load/save, config loading. The `group_display_names` dict maps group keys to display names and is duplicated in `generate_grouped_feed()`, `generate_opml()`, and `generate_html_index()` — update all three when adding a new group.

**`config/sources_config.json`** — Source of truth for all columnist sources. Each entry has: `name`, `url`, `scraper`, `feed_file`, `history_file`, `group`. The `group` field determines which grouped feed the source belongs to.

**`history/`** — JSON files tracking `last_article_link` per source to detect new articles.

**`feeds/`** — Generated output (XML feeds, OPML, HTML). Committed to git and served via GitHub Pages.

## Adding a New Source

1. If the site needs scraping: create a class in `src/scrapers.py` inheriting `BaseScraper`, register it in `get_scraper_class()`.
2. Add entry to `config/sources_config.json`.
3. If using a new `group` value, add its display name to the three `group_display_names` dicts in `src/utils.py`.

## Key Conventions

- All dates use `pytz` timezone-aware datetimes (São Paulo for Brazilian sources, UTC for others).
- `requests_retry_session()` is used for all HTTP requests (3 retries, 30s timeout).
- GitHub Actions workflow commits `feeds/` and `history/` changes automatically with `[skip ci]` in the message.
- The `.venv` directory is not in `.gitignore` but should not be committed (it's local only).
