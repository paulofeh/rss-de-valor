"""Validate the one-time local seed for two newly generated Folha feeds."""

from __future__ import annotations

import json
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET

try:
    from .private_feed_common import (
        CANONICAL_FEED_BASE_URL,
        ConfigurationError,
        PublicationError,
        load_source_inventory,
    )
except ImportError:  # pragma: no cover - direct script execution
    from private_feed_common import (  # type: ignore[no-redef]
        CANONICAL_FEED_BASE_URL,
        ConfigurationError,
        PublicationError,
        load_source_inventory,
    )


PROFILE_NAME = "folha-juliano-sergio-2026-07-27"
EXPECTED_ITEMS_PER_FEED = 10
MIN_DESCRIPTION_CHARACTERS = 500
LEGACY_FEED_BASE_URL = "https://paulofeh.github.io/rss-de-valor"
ATOM_LINK_TAG = "{http://www.w3.org/2005/Atom}link"
DC_CREATOR_TAG = "{http://purl.org/dc/elements/1.1/}creator"
EXPECTED_SOURCES = (
    {
        "name": "Juliano Spyer",
        "url": "https://www1.folha.uol.com.br/colunas/juliano-spyer/",
        "scraper": "FolhaScraper",
        "feed_file": "juliano_spyer_feed.xml",
        "history_file": "juliano_spyer_history.json",
        "group": "folha",
        "slug": "juliano-spyer",
    },
    {
        "name": "Sérgio Rodrigues",
        "url": (
            "https://feeds.folha.uol.com.br/colunas/"
            "sergio-rodrigues/rss091.xml"
        ),
        "scraper": "FolhaRssFullContentScraper",
        "feed_file": "sergio_rodrigues_feed.xml",
        "history_file": "sergio_rodrigues_history.json",
        "group": "folha",
        "slug": "sergio-rodrigues",
    },
)


class FolhaSourceMigrationError(PublicationError):
    """The fixed Folha source-migration seed is absent or divergent."""


def _migration_sources(repo_root: Path) -> list[dict[str, Any]]:
    inventory = load_source_inventory(repo_root)
    sources: list[dict[str, Any]] = []
    for expected in EXPECTED_SOURCES:
        source = next(
            (
                dict(candidate)
                for candidate in inventory.source_by_feed_file.values()
                if candidate.get("name") == expected["name"]
            ),
            None,
        )
        checked_fields = (
            "name",
            "url",
            "scraper",
            "feed_file",
            "history_file",
            "group",
        )
        if source is None or any(
            source.get(field) != expected[field]
            for field in checked_fields
        ):
            raise ConfigurationError(
                f"Folha source migration diverged: {expected['name']}"
            )
        source["slug"] = expected["slug"]
        sources.append(source)
    return sources


def _validate_seed_pair(
    *,
    feed_data: bytes,
    history_data: bytes,
    source: dict[str, Any],
) -> None:
    feed_file = source["feed_file"]
    try:
        root = ET.fromstring(feed_data)
    except ET.ParseError as exc:
        raise FolhaSourceMigrationError(
            f"Folha migration feed is not valid XML: {feed_file}"
        ) from exc
    channel = root.find("channel")
    if channel is None:
        raise FolhaSourceMigrationError(
            f"Folha migration feed has no channel: {feed_file}"
        )

    items = channel.findall("item")
    if len(items) != EXPECTED_ITEMS_PER_FEED:
        raise FolhaSourceMigrationError(
            f"Folha migration feed must contain ten items: {feed_file}"
        )
    self_links = [
        element
        for element in channel.findall(ATOM_LINK_TAG)
        if element.get("rel") == "self"
    ]
    allowed_self_links = {
        f"{CANONICAL_FEED_BASE_URL}/feeds/{feed_file}",
        f"{LEGACY_FEED_BASE_URL}/feeds/{feed_file}",
    }
    if (
        len(self_links) != 1
        or self_links[0].get("href") not in allowed_self_links
    ):
        raise FolhaSourceMigrationError(
            f"Folha migration self-link diverged: {feed_file}"
        )

    links: list[str] = []
    expected_path_prefix = f"/colunas/{source['slug']}/"
    for item in items:
        link = (item.findtext("link") or "").strip()
        guid = (item.findtext("guid") or "").strip()
        author = (item.findtext(DC_CREATOR_TAG) or "").strip()
        description = item.findtext("description") or ""
        pubdate = (item.findtext("pubDate") or "").strip()
        parsed_link = urlsplit(link)
        if (
            parsed_link.scheme != "https"
            or parsed_link.hostname != "www1.folha.uol.com.br"
            or not parsed_link.path.startswith(expected_path_prefix)
            or not parsed_link.path.endswith(".shtml")
            or parsed_link.username
            or parsed_link.password
            or parsed_link.query
            or parsed_link.fragment
        ):
            raise FolhaSourceMigrationError(
                f"Folha migration item URL diverged: {feed_file}"
            )
        if guid != link:
            raise FolhaSourceMigrationError(
                f"Folha migration GUID diverged: {feed_file}"
            )
        if author != source["name"]:
            raise FolhaSourceMigrationError(
                f"Folha migration author diverged: {feed_file}"
            )
        if len(description) < MIN_DESCRIPTION_CHARACTERS:
            raise FolhaSourceMigrationError(
                f"Folha migration content is incomplete: {feed_file}"
            )
        try:
            parsedate_to_datetime(pubdate)
        except (TypeError, ValueError) as exc:
            raise FolhaSourceMigrationError(
                f"Folha migration publication date is invalid: {feed_file}"
            ) from exc
        links.append(link)

    if len(links) != len(set(links)):
        raise FolhaSourceMigrationError(
            f"Folha migration feed contains duplicate items: {feed_file}"
        )
    try:
        history = json.loads(history_data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FolhaSourceMigrationError(
            f"Folha migration history is invalid: {feed_file}"
        ) from exc
    if history != {"last_article_link": links[0]}:
        raise FolhaSourceMigrationError(
            f"Folha migration history diverged: {feed_file}"
        )


def approved_seed_objects(
    *,
    repo_root: Path,
    profile: str,
) -> dict[str, bytes]:
    """Return the four validated local objects approved by the fixed profile."""
    if profile != PROFILE_NAME:
        raise ConfigurationError(
            f"unsupported Folha source migration profile: {profile}"
        )

    repo_root = repo_root.resolve()
    object_data: dict[str, bytes] = {}
    for source in _migration_sources(repo_root):
        feed_path = repo_root / "feeds" / source["feed_file"]
        history_path = repo_root / "history" / source["history_file"]
        if (
            not feed_path.is_file()
            or feed_path.is_symlink()
            or not history_path.is_file()
            or history_path.is_symlink()
        ):
            raise FolhaSourceMigrationError(
                f"Folha migration seed is absent: {source['name']}"
            )
        feed_data = feed_path.read_bytes()
        history_data = history_path.read_bytes()
        _validate_seed_pair(
            feed_data=feed_data,
            history_data=history_data,
            source=source,
        )
        object_data[f"feeds/{source['feed_file']}"] = feed_data
        object_data[f"history/{source['history_file']}"] = history_data

    if len(object_data) != 4:
        raise ConfigurationError(
            "Folha source migration object inventory is invalid"
        )
    return object_data
