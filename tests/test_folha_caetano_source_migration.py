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

from scripts.migrate_folha_caetano_source import (
    CaetanoWGalindoSourceMigrationError,
    PROFILE_NAME,
    approved_seed_objects,
)
from scripts.private_feed_common import CANONICAL_FEED_BASE_URL
from scripts.source_migrations import (
    approved_seed_objects as dispatch_seed_objects,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
ARTICLE_URL = (
    "https://www1.folha.uol.com.br/colunas/caetano-w-galindo/"
    "2026/08/sergio-rodrigues-ajudou-nossa-relacao-com-o-portugues.shtml"
)


def article(**overrides: object) -> dict[str, object]:
    candidate: dict[str, object] = {
        "title": "Sérgio Rodrigues ajudou nossa relação com o português",
        "link": ARTICLE_URL,
        "description": f"<p>{'conteúdo integral ' * 60}</p>",
        "author": "Caetano W. Galindo",
        "pubdate": pytz.timezone("America/Sao_Paulo").localize(
            datetime(2026, 8, 12, 4, 0, 0)
        ),
    }
    candidate.update(overrides)
    return candidate


class CaetanoWGalindoSourceMigrationTest(unittest.TestCase):
    def test_direct_script_import_resolves_repository_packages(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-B",
                "-c",
                (
                    "import source_migrations; "
                    "print(source_migrations.CAETANO_W_GALINDO_PROFILE)"
                ),
            ],
            cwd=REPO_ROOT / "scripts",
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.strip(), PROFILE_NAME)

    @patch("scripts.migrate_folha_caetano_source.FolhaScraper")
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
                "feeds/caetano_w_galindo_feed.xml",
                "history/caetano_w_galindo_history.json",
            },
        )
        self.assertTrue(
            all(isinstance(data, bytes) for data in object_data.values())
        )
        scraper_class.assert_called_once_with(
            "https://www1.folha.uol.com.br/colunas/caetano-w-galindo/"
        )
        scraper_class.return_value.get_articles.assert_called_once_with(
            limit=10
        )

        root = ET.fromstring(
            object_data["feeds/caetano_w_galindo_feed.xml"]
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
                "caetano_w_galindo_feed.xml"
            ),
        )
        self.assertEqual(
            json.loads(
                object_data["history/caetano_w_galindo_history.json"]
            ),
            {"last_article_link": ARTICLE_URL},
        )

    @patch("scripts.migrate_folha_caetano_source.FolhaScraper")
    def test_rejects_off_scope_articles(
        self,
        scraper_class: MagicMock,
    ) -> None:
        scraper_class.return_value.get_articles.return_value = [
            article(
                link=(
                    "https://www1.folha.uol.com.br/colunas/"
                    "outra-coluna/2026/08/artigo.shtml"
                )
            )
        ]

        with self.assertRaisesRegex(
            CaetanoWGalindoSourceMigrationError,
            "off-scope URL",
        ):
            approved_seed_objects(
                repo_root=REPO_ROOT,
                profile=PROFILE_NAME,
            )


if __name__ == "__main__":
    unittest.main()
