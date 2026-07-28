from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

from scripts.migrate_folha_sources import (
    ATOM_LINK_TAG,
    EXPECTED_SOURCES,
    LEGACY_FEED_BASE_URL,
    PROFILE_NAME,
    FolhaSourceMigrationError,
    approved_seed_objects,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


class FolhaSourceMigrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "config").mkdir()
        (self.root / "feeds").mkdir()
        (self.root / "history").mkdir()
        shutil.copyfile(
            REPO_ROOT / "config" / "sources_config.json",
            self.root / "config" / "sources_config.json",
        )
        for source in EXPECTED_SOURCES:
            shutil.copyfile(
                REPO_ROOT / "feeds" / source["feed_file"],
                self.root / "feeds" / source["feed_file"],
            )
            shutil.copyfile(
                REPO_ROOT / "history" / source["history_file"],
                self.root / "history" / source["history_file"],
            )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_accepts_exact_legacy_pages_self_link_only_as_seed(self) -> None:
        source = EXPECTED_SOURCES[0]
        feed_path = self.root / "feeds" / source["feed_file"]
        tree = ET.parse(feed_path)
        self_link = tree.getroot().find(f"./channel/{ATOM_LINK_TAG}")
        self.assertIsNotNone(self_link)
        self_link.set(
            "href",
            f"{LEGACY_FEED_BASE_URL}/feeds/{source['feed_file']}",
        )
        tree.write(feed_path, encoding="utf-8", xml_declaration=True)

        object_data = approved_seed_objects(
            repo_root=self.root,
            profile=PROFILE_NAME,
        )

        self.assertEqual(len(object_data), 4)
        self.assertEqual(
            object_data[f"feeds/{source['feed_file']}"],
            feed_path.read_bytes(),
        )

    def test_rejects_history_that_does_not_match_latest_item(self) -> None:
        source = EXPECTED_SOURCES[1]
        history_path = self.root / "history" / source["history_file"]
        history_path.write_text(
            json.dumps(
                {"last_article_link": "https://example.invalid/divergent"}
            ),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(
            FolhaSourceMigrationError,
            "history diverged",
        ):
            approved_seed_objects(
                repo_root=self.root,
                profile=PROFILE_NAME,
            )


if __name__ == "__main__":
    unittest.main()
