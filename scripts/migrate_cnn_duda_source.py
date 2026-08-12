"""Build and validate the one-time seed for Duda Herriot's CNN feed."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from src.scrapers import CNNBrasilBlogScraper
from src.utils import generate_feed

try:
    from .private_feed_common import (
        ConfigurationError,
        PublicationError,
        load_source_inventory,
    )
except ImportError:  # pragma: no cover - direct script execution
    from private_feed_common import (  # type: ignore[no-redef]
        ConfigurationError,
        PublicationError,
        load_source_inventory,
    )


PROFILE_NAME = "cnn-duda-herriot-2026-08-12"
MAX_ITEMS = 10
MIN_DESCRIPTION_CHARACTERS = 500
EXPECTED_SOURCE = {
    "name": "Duda Herriot (CNN Brasil)",
    "url": "https://www.cnnbrasil.com.br/colunas/duda-herriot/",
    "scraper": "CNNBrasilBlogScraper",
    "feed_file": "duda_herriot_feed.xml",
    "history_file": "duda_herriot_history.json",
    "group": "outros",
}


class DudaHerriotSourceMigrationError(PublicationError):
    """The fixed Duda Herriot source seed is absent or divergent."""


def _migration_source(repo_root: Path) -> dict[str, Any]:
    inventory = load_source_inventory(repo_root)
    source = inventory.source_by_feed_file.get(EXPECTED_SOURCE["feed_file"])
    if source is None or any(
        source.get(field) != value
        for field, value in EXPECTED_SOURCE.items()
    ):
        raise ConfigurationError("Duda Herriot source migration diverged")
    return dict(source)


def _validate_articles(articles: list[dict[str, Any]]) -> None:
    if not 1 <= len(articles) <= MAX_ITEMS:
        raise DudaHerriotSourceMigrationError(
            "Duda Herriot migration returned an invalid article count"
        )

    links: list[str] = []
    for article in articles:
        link = article.get("link", "")
        parsed = urlsplit(link)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "www.cnnbrasil.com.br"
            or not parsed.path.startswith("/colunas/duda-herriot/")
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise DudaHerriotSourceMigrationError(
                "Duda Herriot migration returned an off-scope URL"
            )
        if article.get("author") != "Duda Herriot":
            raise DudaHerriotSourceMigrationError(
                "Duda Herriot migration returned an unexpected author"
            )
        if not str(article.get("title", "")).strip():
            raise DudaHerriotSourceMigrationError(
                "Duda Herriot migration returned an empty title"
            )
        if len(str(article.get("description", ""))) < MIN_DESCRIPTION_CHARACTERS:
            raise DudaHerriotSourceMigrationError(
                "Duda Herriot migration returned incomplete content"
            )
        pubdate = article.get("pubdate")
        if (
            pubdate is None
            or pubdate.tzinfo is None
            or pubdate.utcoffset() is None
        ):
            raise DudaHerriotSourceMigrationError(
                "Duda Herriot migration returned a naive publication date"
            )
        links.append(link)

    if len(links) != len(set(links)):
        raise DudaHerriotSourceMigrationError(
            "Duda Herriot migration returned duplicate articles"
        )


def approved_seed_objects(
    *,
    repo_root: Path,
    profile: str,
) -> dict[str, bytes]:
    """Return the two live-validated objects approved by the fixed profile."""
    if profile != PROFILE_NAME:
        raise ConfigurationError(
            f"unsupported Duda Herriot source migration profile: {profile}"
        )

    source = _migration_source(repo_root.resolve())
    articles = CNNBrasilBlogScraper(source["url"]).get_articles(
        limit=MAX_ITEMS
    )
    _validate_articles(articles)

    feed = generate_feed(
        source["name"],
        source["url"],
        articles,
        feed_filename=source["feed_file"],
    )
    feed_data = feed.writeString("utf-8")
    history_data = json.dumps(
        {"last_article_link": articles[0]["link"]},
        ensure_ascii=False,
    ).encode("utf-8")
    return {
        f"feeds/{source['feed_file']}": feed_data,
        f"history/{source['history_file']}": history_data,
    }
