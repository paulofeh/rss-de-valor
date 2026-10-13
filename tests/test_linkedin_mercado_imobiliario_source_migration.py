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

from scripts.migrate_linkedin_mercado_imobiliario_source import (
    MercadoImobiliarioSourceMigrationError,
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
    "mercado-imobili%C3%A1rio-e-economia-7446891948260425728/"
)
ARTICLE_URL = (
    "https://pt.linkedin.com/pulse/"
    "financiamento-imobiliario-ara%C3%BAjo-fikff"
)


def article(**overrides: object) -> dict[str, object]:
    candidate: dict[str, object] = {
        "title": "Financiamento Imobiliário",
        "link": ARTICLE_URL,
        "description": f"<p>{'conteúdo integral ' * 60}</p>",
        "author": "Fábio Tadeu Araújo",
        "pubdate": pytz.UTC.localize(datetime(2026, 10, 7, 13, 46, 16)),
        "_enrichment_failed": False,
    }
    candidate.update(overrides)
    return candidate


class MercadoImobiliarioSourceMigrationTest(unittest.TestCase):
    @patch("scripts.migrate_linkedin_mercado_imobiliario_source.LinkedInNewsletterScraper")
    def test_rejects_invalid_seed_content(self, scraper_class: MagicMock) -> None:
        cases = [
            ([], "invalid article count"),
            ([article()] * 6, "invalid article count"),
            ([article(), article()], "duplicate articles"),
            ([article(author="Outro Araújo")], "unexpected author"),
            ([article(description="Resumo curto")], "incomplete content"),
            ([article(title=" ")], "empty title"),
            ([article(pubdate=datetime(2026, 10, 7))], "naive publication date"),
            ([article(link=ARTICLE_URL + "?tracking=yes")], "off-scope URL"),
            ([article(link=ARTICLE_URL.replace("https://", "https://user:secret@"))], "off-scope URL"),
        ]
        for articles, error in cases:
            with self.subTest(error=error, articles=len(articles)):
                scraper_class.return_value.get_articles.return_value = articles
                with self.assertRaisesRegex(MercadoImobiliarioSourceMigrationError, error):
                    approved_seed_objects(repo_root=REPO_ROOT, profile=PROFILE_NAME)

    def test_direct_script_import_resolves_repository_packages(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-B",
                "-c",
                (
                    "import source_migrations; "
                    "print(source_migrations.MERCADO_IMOBILIARIO_PROFILE)"
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
        "scripts.migrate_linkedin_mercado_imobiliario_source.LinkedInNewsletterScraper"
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
                "feeds/mercado_imobiliario_e_economia_linkedin_feed.xml",
                "history/mercado_imobiliario_e_economia_linkedin_history.json",
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
            object_data["feeds/mercado_imobiliario_e_economia_linkedin_feed.xml"]
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
                "mercado_imobiliario_e_economia_linkedin_feed.xml"
            ),
        )
        self.assertEqual(
            json.loads(
                object_data[
                    "history/mercado_imobiliario_e_economia_linkedin_history.json"
                ]
            ),
            {"last_article_link": ARTICLE_URL},
        )

    @patch(
        "scripts.migrate_linkedin_mercado_imobiliario_source.LinkedInNewsletterScraper"
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
            MercadoImobiliarioSourceMigrationError,
            "off-scope URL",
        ):
            approved_seed_objects(
                repo_root=REPO_ROOT,
                profile=PROFILE_NAME,
            )

    @patch(
        "scripts.migrate_linkedin_mercado_imobiliario_source.LinkedInNewsletterScraper"
    )
    def test_rejects_failed_enrichment(
        self,
        scraper_class: MagicMock,
    ) -> None:
        scraper_class.return_value.get_articles.return_value = [
            article(_enrichment_failed=True)
        ]

        with self.assertRaisesRegex(
            MercadoImobiliarioSourceMigrationError,
            "failed enrichment",
        ):
            approved_seed_objects(
                repo_root=REPO_ROOT,
                profile=PROFILE_NAME,
            )


if __name__ == "__main__":
    unittest.main()
