from __future__ import annotations

import html
import json
import tempfile
import unittest
from pathlib import Path

from scripts.repair_linkedin_baseline import (
    BaselineRepairError,
    ConfigurationError,
    EXPECTED_OBJECT_COUNT,
    EXPECTED_SOURCE_COUNT,
    PROFILE_NAME,
    REPAIR_SOURCE_NAMES,
    approved_repair_feed_files,
    restore_repair_baseline,
    stage_repair_baseline,
)


def write_linkedin_feed(
    path: Path,
    *,
    feed_file: str,
    source_index: int,
    author: str,
) -> list[str]:
    items = []
    links = []
    for item_index in range(5):
        link = (
            "https://www.linkedin.com/pulse/"
            f"article-{source_index}-{item_index}"
        )
        links.append(link)
        description = f"<p>{'complete content ' * 40}</p>"
        items.append(
            f"""
    <item>
      <title>Article {source_index}-{item_index}</title>
      <link>{html.escape(link)}</link>
      <description>{html.escape(description)}</description>
      <dc:creator>{html.escape(author)}</dc:creator>
      <pubDate>Mon, 27 Jul 2026 12:00:00 +0000</pubDate>
      <guid>{html.escape(link)}</guid>
    </item>"""
        )
    value = f"""<?xml version="1.0" encoding="utf-8"?>
<rss xmlns:atom="http://www.w3.org/2005/Atom"
     xmlns:dc="http://purl.org/dc/elements/1.1/"
     version="2.0">
  <channel>
    <title>LinkedIn test feed</title>
    <link>https://www.linkedin.com/newsletters/{source_index}/</link>
    <description>Test feed</description>
    <atom:link
      href="https://paulofeh.github.io/rss-de-valor/feeds/{feed_file}"
      rel="self" />
    {''.join(items)}
  </channel>
</rss>
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    return links


def create_repair_repository(root: Path) -> list[dict[str, str]]:
    (root / "config").mkdir(parents=True)
    (root / "feeds").mkdir()
    (root / "history").mkdir()
    sources = []
    for index, name in enumerate(sorted(REPAIR_SOURCE_NAMES)):
        feed_file = f"linkedin_{index:02d}_feed.xml"
        history_file = f"linkedin_{index:02d}_history.json"
        source = {
            "name": name,
            "url": f"https://www.linkedin.com/newsletters/{index}/",
            "scraper": "LinkedInNewsletterScraper",
            "feed_file": feed_file,
            "history_file": history_file,
            "group": "linkedin",
        }
        sources.append(source)
        links = write_linkedin_feed(
            root / "feeds" / feed_file,
            feed_file=feed_file,
            source_index=index,
            author=f"Author {index}",
        )
        (root / "history" / history_file).write_text(
            json.dumps({"last_article_link": links[0]}),
            encoding="utf-8",
        )
    (root / "config" / "sources_config.json").write_text(
        json.dumps({"sources": sources}, ensure_ascii=False),
        encoding="utf-8",
    )
    return sources


class LinkedInBaselineRepairTest(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = tempfile.TemporaryDirectory()
        self.staging = tempfile.TemporaryDirectory()
        self.root = Path(self.repository.name)
        self.stage_dir = Path(self.staging.name) / "stage"
        self.sources = create_repair_repository(self.root)

    def tearDown(self) -> None:
        self.staging.cleanup()
        self.repository.cleanup()

    def test_stage_and_restore_exact_validated_inventory(self) -> None:
        self.assertEqual(
            len(
                approved_repair_feed_files(
                    repo_root=self.root,
                    profile=PROFILE_NAME,
                )
            ),
            EXPECTED_SOURCE_COUNT,
        )
        staged = stage_repair_baseline(
            repo_root=self.root,
            stage_dir=self.stage_dir,
        )
        self.assertEqual(staged["status"], "staged")
        self.assertEqual(staged["sources"], EXPECTED_SOURCE_COUNT)
        self.assertEqual(staged["objects"], EXPECTED_OBJECT_COUNT)

        manifest = json.loads(
            (self.stage_dir / "manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(len(manifest["objects"]), EXPECTED_OBJECT_COUNT)
        expected_data = {
            object_path: (
                self.stage_dir / "objects" / object_path
            ).read_bytes()
            for object_path in manifest["objects"]
        }
        for object_path in expected_data:
            (self.root / object_path).write_bytes(b"hydrated remote sentinel")

        restored = restore_repair_baseline(
            repo_root=self.root,
            stage_dir=self.stage_dir,
        )

        self.assertEqual(restored["status"], "restored")
        self.assertEqual(restored["sources"], EXPECTED_SOURCE_COUNT)
        self.assertEqual(restored["objects"], EXPECTED_OBJECT_COUNT)
        for object_path, expected in expected_data.items():
            self.assertEqual((self.root / object_path).read_bytes(), expected)

    def test_restore_rejects_tampering_before_replacing_hydrated_files(
        self,
    ) -> None:
        stage_repair_baseline(
            repo_root=self.root,
            stage_dir=self.stage_dir,
        )
        target = self.sources[0]
        object_path = f"feeds/{target['feed_file']}"
        (self.stage_dir / "objects" / object_path).write_bytes(b"tampered")
        destination = self.root / object_path
        destination.write_bytes(b"hydrated remote sentinel")

        with self.assertRaisesRegex(
            BaselineRepairError,
            "staged artifact diverged",
        ):
            restore_repair_baseline(
                repo_root=self.root,
                stage_dir=self.stage_dir,
            )

        self.assertEqual(
            destination.read_bytes(),
            b"hydrated remote sentinel",
        )

    def test_stage_rejects_incomplete_checked_in_feed(self) -> None:
        target = self.sources[0]
        feed_path = self.root / "feeds" / target["feed_file"]
        value = feed_path.read_text(encoding="utf-8").replace(
            "Author 0",
            "Autor não encontrado",
            1,
        )
        feed_path.write_text(value, encoding="utf-8")

        with self.assertRaisesRegex(
            BaselineRepairError,
            "author is absent",
        ):
            stage_repair_baseline(
                repo_root=self.root,
                stage_dir=self.stage_dir,
            )

        self.assertFalse(self.stage_dir.exists())

    def test_stage_rejects_non_linkedin_target_source(self) -> None:
        config_path = self.root / "config" / "sources_config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["sources"][0]["scraper"] = "OtherScraper"
        config_path.write_text(json.dumps(config), encoding="utf-8")

        with self.assertRaisesRegex(
            ConfigurationError,
            "must use LinkedInNewsletterScraper",
        ):
            stage_repair_baseline(
                repo_root=self.root,
                stage_dir=self.stage_dir,
            )

    def test_repair_feed_allowlist_rejects_unknown_profile(self) -> None:
        with self.assertRaisesRegex(
            ConfigurationError,
            "unsupported LinkedIn baseline repair profile",
        ):
            approved_repair_feed_files(
                repo_root=self.root,
                profile="unknown-repair",
            )


if __name__ == "__main__":
    unittest.main()
