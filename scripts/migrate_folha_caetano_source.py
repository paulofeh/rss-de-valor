"""Build and validate the one-time seed for Caetano W. Galindo's feed."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

try:
    from src.scrapers import FolhaScraper
    from src.utils import generate_feed
except ModuleNotFoundError as exc:  # pragma: no cover - direct execution
    if exc.name != "src":
        raise
    repo_root = str(Path(__file__).resolve().parents[1])
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    from src.scrapers import FolhaScraper
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


PROFILE_NAME = "folha-caetano-w-galindo-2026-08-13"
MAX_ITEMS = 10
MIN_DESCRIPTION_CHARACTERS = 500
EXPECTED_AUTHOR = "Caetano W. Galindo"
EXPECTED_PATH_PREFIX = "/colunas/caetano-w-galindo/"
EXPECTED_SOURCE = {
    "name": EXPECTED_AUTHOR,
    "url": "https://www1.folha.uol.com.br/colunas/caetano-w-galindo/",
    "scraper": "FolhaScraper",
    "feed_file": "caetano_w_galindo_feed.xml",
    "history_file": "caetano_w_galindo_history.json",
    "group": "folha",
}


class CaetanoWGalindoSourceMigrationError(PublicationError):
    """The fixed Caetano W. Galindo source seed is absent or divergent."""


def _migration_source(repo_root: Path) -> dict[str, Any]:
    inventory = load_source_inventory(repo_root)
    source = inventory.source_by_feed_file.get(EXPECTED_SOURCE["feed_file"])
    if source is None or any(
        source.get(field) != value
        for field, value in EXPECTED_SOURCE.items()
    ):
        raise ConfigurationError(
            "Caetano W. Galindo source migration diverged"
        )
    return dict(source)


def _validate_articles(articles: list[dict[str, Any]]) -> None:
    if not 1 <= len(articles) <= MAX_ITEMS:
        raise CaetanoWGalindoSourceMigrationError(
            "Caetano W. Galindo migration returned an invalid article count"
        )

    links: list[str] = []
    for article in articles:
        link = article.get("link", "")
        parsed = urlsplit(link)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "www1.folha.uol.com.br"
            or not parsed.path.startswith(EXPECTED_PATH_PREFIX)
            or not parsed.path.endswith(".shtml")
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise CaetanoWGalindoSourceMigrationError(
                "Caetano W. Galindo migration returned an off-scope URL"
            )
        if article.get("author") != EXPECTED_AUTHOR:
            raise CaetanoWGalindoSourceMigrationError(
                "Caetano W. Galindo migration returned an unexpected author"
            )
        if not str(article.get("title", "")).strip():
            raise CaetanoWGalindoSourceMigrationError(
                "Caetano W. Galindo migration returned an empty title"
            )
        if len(str(article.get("description", ""))) < (
            MIN_DESCRIPTION_CHARACTERS
        ):
            raise CaetanoWGalindoSourceMigrationError(
                "Caetano W. Galindo migration returned incomplete content"
            )
        pubdate = article.get("pubdate")
        if (
            pubdate is None
            or pubdate.tzinfo is None
            or pubdate.utcoffset() is None
        ):
            raise CaetanoWGalindoSourceMigrationError(
                "Caetano W. Galindo migration returned a naive publication date"
            )
        links.append(link)

    if len(links) != len(set(links)):
        raise CaetanoWGalindoSourceMigrationError(
            "Caetano W. Galindo migration returned duplicate articles"
        )


def approved_seed_objects(
    *,
    repo_root: Path,
    profile: str,
) -> dict[str, bytes]:
    """Return the two live-validated objects approved by the fixed profile."""
    if profile != PROFILE_NAME:
        raise ConfigurationError(
            "unsupported Caetano W. Galindo source migration profile: "
            f"{profile}"
        )

    source = _migration_source(repo_root.resolve())
    articles = FolhaScraper(source["url"]).get_articles(limit=MAX_ITEMS)
    _validate_articles(articles)

    feed = generate_feed(
        source["name"],
        source["url"],
        articles,
        feed_filename=source["feed_file"],
    )
    feed_data = feed.writeString("utf-8").encode("utf-8")
    history_data = json.dumps(
        {"last_article_link": articles[0]["link"]},
        ensure_ascii=False,
    ).encode("utf-8")
    return {
        f"feeds/{source['feed_file']}": feed_data,
        f"history/{source['history_file']}": history_data,
    }
