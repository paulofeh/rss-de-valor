"""Define the one-time Martin Wolf publication-date repair.

The legacy Folha scraper attached a pytz timezone with ``replace()``, which
serialized one known item with São Paulo's historical local-mean-time offset
(``-03:06``). The full-content RSS scraper correctly emits the same local time
as UTC. This module describes the only transition that a confirmed manual
private publication may accept.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

try:
    from .private_feed_common import ConfigurationError, load_source_inventory
except ImportError:  # pragma: no cover - direct script execution
    from private_feed_common import (  # type: ignore[no-redef]
        ConfigurationError,
        load_source_inventory,
    )


PROFILE_NAME = "martin-wolf-pubdate-2026-07-27"
SOURCE_NAME = "Martin Wolf"
SOURCE_URL = (
    "https://feeds.folha.uol.com.br/colunas/martinwolf/rss091.xml"
)
SCRAPER = "FolhaRssFullContentScraper"
FEED_FILE = "martin_wolf_feed.xml"
HISTORY_FILE = "martin_wolf_history.json"
SOURCE_GROUP = "folha"
ARTICLE_URL = (
    "https://www1.folha.uol.com.br/colunas/martinwolf/2026/07/"
    "quem-vencera-a-guerra-dos-neomercantilistas.shtml"
)
BASELINE_PUBDATE = "Wed, 22 Jul 2026 20:30:00 -0306"
CURRENT_PUBDATE = "Wed, 22 Jul 2026 23:30:00 +0000"


@dataclass(frozen=True)
class ApprovedPubdateRepair:
    """An immutable, article-level publication-date transition."""

    feed_file: str
    article_url: str
    baseline_pubdate: str
    current_pubdate: str


def approved_pubdate_repair(
    *,
    repo_root: Path,
    profile: str,
) -> ApprovedPubdateRepair:
    """Resolve the fixed repair only while source configuration is unchanged."""
    if profile != PROFILE_NAME:
        raise ConfigurationError(
            "unsupported Martin Wolf publication-date repair profile: "
            f"{profile}"
        )

    inventory = load_source_inventory(repo_root.resolve())
    source = inventory.source_by_feed_file.get(FEED_FILE)
    expected = {
        "name": SOURCE_NAME,
        "url": SOURCE_URL,
        "scraper": SCRAPER,
        "feed_file": FEED_FILE,
        "history_file": HISTORY_FILE,
        "group": SOURCE_GROUP,
    }
    if source is None or any(
        source.get(field) != value for field, value in expected.items()
    ):
        raise ConfigurationError(
            "Martin Wolf publication-date repair source diverged"
        )

    return ApprovedPubdateRepair(
        feed_file=FEED_FILE,
        article_url=ARTICLE_URL,
        baseline_pubdate=BASELINE_PUBDATE,
        current_pubdate=CURRENT_PUBDATE,
    )
