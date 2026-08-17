from __future__ import annotations

import json
import subprocess
import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch
from xml.etree import ElementTree as ET

import pytz

from scripts.migrate_linkedin_elcio_source import (
    ElcioBatistaSourceMigrationError,
    PROFILE_NAME,
    approved_seed_objects,
)
from scripts.private_feed_common import CANONICAL_FEED_BASE_URL
from scripts.source_migrations import (
    approved_seed_objects as dispatch_seed_objects,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
NEWSLETTER_URL = (
    "https://www.linkedin.com/newsletters/"
    "entre-vozes-e-caminhos-7307792015079972865/"
)
ARTICLE_URL = (
    "https://pt.linkedin.com/pulse/"
    "cidade-e-o-tempo-%C3%A9lcio-batista-s2d9f"
)


def article(**overrides: object) -> dict[str, object]:
    candidate: dict[str, object] = {
        "title": "A cidade e o tempo",
        "link": ARTICLE_URL,
        "description": f"<p>{'conteúdo integral ' * 60}</p>",
        "author": "Élcio Batista",
        "pubdate": pytz.UTC.localize(datetime(2026, 8, 16, 19, 45, 23)),
        "_enrichment_failed": False,
    }
    candidate.update(overrides)
    return candidate


class ElcioBatistaSourceMigrationTest(unittest.TestCase):
    def test_direct_script_import_resolves_repository_packages(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-B",
                "-c",
                (
                    "import source_migrations; "
                    "print(source_migrations.ELCIO_BATISTA_PROFILE)"
                ),
            ],
            cwd=REPO_ROOT / "scripts",
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.strip(), PROFILE_NAME)

    @patch(
        "scripts.migrate_linkedin_elcio_source.LinkedInNewsletterScraper"
    )
    def test_dispatch_builds_only_the_validated_feed_and_history(
        self,
        scraper_class: MagicMock,
    ) -> None:
        scraper_class.return_value.get_articles.return_value = [article()]

        object_data = dispatch_seed_objects(
            repo_root=REPO_ROOT,
            profile=PROFILE_NAME,
        )

        self.assertEqual(
            set(object_data),
            {
                "feeds/elcio_batista_linkedin_feed.xml",
                "history/elcio_batista_linkedin_history.json",
            },
        )
        self.assertTrue(
            all(isinstance(data, bytes) for data in object_data.values())
        )
        scraper_class.assert_called_once_with(NEWSLETTER_URL)
        scraper_class.return_value.get_articles.assert_called_once_with(
            limit=5
        )

        root = ET.fromstring(
            object_data["feeds/elcio_batista_linkedin_feed.xml"]
        )
        channel = root.find("channel")
        self.assertIsNotNone(channel)
        assert channel is not None
        item = channel.find("item")
        self.assertIsNotNone(item)
        assert item is not None
        self.assertEqual(item.findtext("link"), ARTICLE_URL)
        self.assertEqual(
            channel.find("{http://www.w3.org/2005/Atom}link").get("href"),
            (
                f"{CANONICAL_FEED_BASE_URL}/feeds/"
                "elcio_batista_linkedin_feed.xml"
            ),
        )
        self.assertEqual(
            json.loads(
                object_data[
                    "history/elcio_batista_linkedin_history.json"
                ]
            ),
            {"last_article_link": ARTICLE_URL},
        )

    @patch(
        "scripts.migrate_linkedin_elcio_source.LinkedInNewsletterScraper"
    )
    def test_rejects_off_scope_articles(
        self,
        scraper_class: MagicMock,
    ) -> None:
        scraper_class.return_value.get_articles.return_value = [
            article(
                link=(
                    "https://pt.linkedin.com/pulse/"
                    "artigo-de-outro-autor-abcde"
                )
            )
        ]

        with self.assertRaisesRegex(
            ElcioBatistaSourceMigrationError,
            "off-scope URL",
        ):
            approved_seed_objects(
                repo_root=REPO_ROOT,
                profile=PROFILE_NAME,
            )

    @patch(
        "scripts.migrate_linkedin_elcio_source.LinkedInNewsletterScraper"
    )
    def test_rejects_failed_enrichment(
        self,
        scraper_class: MagicMock,
    ) -> None:
        scraper_class.return_value.get_articles.return_value = [
            article(_enrichment_failed=True)
        ]

        with self.assertRaisesRegex(
            ElcioBatistaSourceMigrationError,
            "failed enrichment",
        ):
            approved_seed_objects(
                repo_root=REPO_ROOT,
                profile=PROFILE_NAME,
            )


if __name__ == "__main__":
    unittest.main()
