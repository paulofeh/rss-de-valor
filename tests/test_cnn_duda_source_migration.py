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

from scripts.migrate_cnn_duda_source import (
    DudaHerriotSourceMigrationError,
    PROFILE_NAME,
    approved_seed_objects,
)
from scripts.private_feed_common import CANONICAL_FEED_BASE_URL


REPO_ROOT = Path(__file__).resolve().parents[1]
ARTICLE_URL = (
    "https://www.cnnbrasil.com.br/colunas/duda-herriot/"
    "economia/negocios/cidades-avisam-que-bairros-podem-valorizar-entenda/"
)


def article(**overrides: object) -> dict[str, object]:
    candidate: dict[str, object] = {
        "title": "Cidades avisam que bairros podem valorizar?",
        "link": ARTICLE_URL,
        "description": f"<p>{'conteúdo integral ' * 60}</p>",
        "author": "Duda Herriot",
        "pubdate": pytz.timezone("America/Sao_Paulo").localize(
            datetime(2026, 8, 11, 11, 9, 42)
        ),
    }
    candidate.update(overrides)
    return candidate


class DudaHerriotSourceMigrationTest(unittest.TestCase):
    def test_direct_script_import_resolves_repository_packages(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-B",
                "-c",
                (
                    "import source_migrations; "
                    "print(source_migrations.DUDA_HERRIOT_PROFILE)"
                ),
            ],
            cwd=REPO_ROOT / "scripts",
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.strip(), PROFILE_NAME)

    @patch("scripts.migrate_cnn_duda_source.CNNBrasilBlogScraper")
    def test_builds_only_the_validated_feed_and_history(
        self,
        scraper_class: MagicMock,
    ) -> None:
        scraper_class.return_value.get_articles.return_value = [article()]

        object_data = approved_seed_objects(
            repo_root=REPO_ROOT,
            profile=PROFILE_NAME,
        )

        self.assertEqual(
            set(object_data),
            {
                "feeds/duda_herriot_feed.xml",
                "history/duda_herriot_history.json",
            },
        )
        self.assertTrue(
            all(isinstance(data, bytes) for data in object_data.values())
        )
        scraper_class.assert_called_once_with(
            "https://www.cnnbrasil.com.br/colunas/duda-herriot/"
        )
        scraper_class.return_value.get_articles.assert_called_once_with(
            limit=10
        )

        root = ET.fromstring(object_data["feeds/duda_herriot_feed.xml"])
        channel = root.find("channel")
        self.assertIsNotNone(channel)
        assert channel is not None
        item = channel.find("item")
        self.assertIsNotNone(item)
        assert item is not None
        self.assertEqual(item.findtext("link"), ARTICLE_URL)
        self.assertEqual(
            channel.find("{http://www.w3.org/2005/Atom}link").get("href"),
            f"{CANONICAL_FEED_BASE_URL}/feeds/duda_herriot_feed.xml",
        )
        self.assertEqual(
            json.loads(
                object_data["history/duda_herriot_history.json"]
            ),
            {"last_article_link": ARTICLE_URL},
        )

    @patch("scripts.migrate_cnn_duda_source.CNNBrasilBlogScraper")
    def test_rejects_off_scope_articles(
        self,
        scraper_class: MagicMock,
    ) -> None:
        scraper_class.return_value.get_articles.return_value = [
            article(link="https://www.cnnbrasil.com.br/economia/noticia/")
        ]

        with self.assertRaisesRegex(
            DudaHerriotSourceMigrationError,
            "off-scope URL",
        ):
            approved_seed_objects(
                repo_root=REPO_ROOT,
                profile=PROFILE_NAME,
            )


if __name__ == "__main__":
    unittest.main()
