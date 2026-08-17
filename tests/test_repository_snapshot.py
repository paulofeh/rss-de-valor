from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.build_snapshot_manifest import build_snapshot
from scripts.private_feed_common import (
    CANONICAL_FEED_BASE_URL,
    build_object_specs,
    load_publication_policy,
    load_source_inventory,
)
from scripts.validate_snapshot import validate_working_state
from tests.private_publication_helpers import write_feed, write_opml


REPO_ROOT = Path(__file__).resolve().parents[1]


class RepositorySnapshotIntegrationTest(unittest.TestCase):
    def test_actual_inventory_builds_from_synthetic_runtime_state(
        self,
    ) -> None:
        inventory = load_source_inventory(REPO_ROOT)
        policy = load_publication_policy(REPO_ROOT)
        specs = build_object_specs(REPO_ROOT, inventory, policy)

        self.assertEqual(len(inventory.generated_feed_files), 111)
        self.assertEqual(len(inventory.generated_history_files), 111)
        self.assertEqual(len(inventory.native_sources), 1)
        self.assertEqual(len(specs), 223)

        with tempfile.TemporaryDirectory(
            prefix="rss-private-repository-snapshot-"
        ) as temporary:
            root = Path(temporary)
            (root / "config").mkdir()
            (root / "feeds").mkdir()
            (root / "history").mkdir()
            for name in (
                "sources_config.json",
                "private_publication_allowlist.json",
            ):
                shutil.copyfile(
                    REPO_ROOT / "config" / name,
                    root / "config" / name,
                )

            sources = json.loads(
                (root / "config" / "sources_config.json").read_text(
                    encoding="utf-8"
                )
            )["sources"]
            generated_sources = [
                source
                for source in sources
                if source["scraper"] != "ExistingRssScraper"
            ]
            for index, source in enumerate(generated_sources):
                article_url = (
                    f"https://publisher.example/article-{index}"
                )
                write_feed(
                    root / "feeds" / source["feed_file"],
                    self_url=(
                        f"{CANONICAL_FEED_BASE_URL}/feeds/"
                        f"{source['feed_file']}"
                    ),
                    article_url=article_url,
                    description=f"<p>{'conteudo ' * 90}</p>",
                    author=source["name"],
                )
                (
                    root / "history" / source["history_file"]
                ).write_text(
                    json.dumps({"last_article_link": article_url}),
                    encoding="utf-8",
                )
            write_opml(root / "feeds" / "feeds.opml", sources)

            report = validate_working_state(
                repo_root=root,
                feed_base_url=CANONICAL_FEED_BASE_URL,
                mode="full",
                pilot_feed_file=None,
                baseline_dir=None,
            )
            snapshot, manifest = build_snapshot(
                repo_root=root,
                output_root=root / ".private-feed-build",
                feed_base_url=CANONICAL_FEED_BASE_URL,
                mode="full",
                pilot_feed_file=None,
                canary_feed_file=inventory.generated_feed_files[0],
                baseline_dir=None,
                state_dir=root / ".private-feed-state",
                run_id="actual-inventory-integration",
                revision="test-revision",
            )

            self.assertEqual(report.generated_feeds, 111)
            self.assertEqual(manifest["counts"]["objects"], 223)
            self.assertEqual(manifest["counts"]["routes"], 112)
            self.assertTrue((snapshot / "manifest.json").is_file())


if __name__ == "__main__":
    unittest.main()
