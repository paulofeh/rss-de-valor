from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET

from scripts.build_snapshot_manifest import build_snapshot
from scripts.private_feed_common import (
    CANONICAL_FEED_BASE_URL,
    build_object_specs,
    load_publication_policy,
    load_source_inventory,
)
from scripts.validate_snapshot import validate_working_state
from src.utils import generate_opml, save_opml


REPO_ROOT = Path(__file__).resolve().parents[1]
ATOM_LINK = "{http://www.w3.org/2005/Atom}link"
EXPECTED_EXTRA_XML = {
    "alice_ferraz_feed.xml",
    "andre_derviche_feed.xml",
    "estadao_feed.xml",
    "felipe_salto_feed.xml",
    "folha_feed.xml",
    "linkedin_feed.xml",
    "oglobo_feed.xml",
    "outros_feed.xml",
    "poder360_feed.xml",
    "valor_feed.xml",
}


class RepositorySnapshotIntegrationTest(unittest.TestCase):
    def test_actual_inventory_builds_an_allowlisted_canonical_snapshot(
        self,
    ) -> None:
        inventory = load_source_inventory(REPO_ROOT)
        policy = load_publication_policy(REPO_ROOT)
        specs = build_object_specs(REPO_ROOT, inventory, policy)
        configured_xml = set(inventory.source_by_feed_file)
        disk_xml = {
            path.name for path in (REPO_ROOT / "feeds").glob("*.xml")
        }

        self.assertEqual(len(inventory.generated_feed_files), 107)
        self.assertEqual(len(inventory.generated_history_files), 107)
        self.assertEqual(len(inventory.native_sources), 2)
        self.assertEqual(len(specs), 215)
        self.assertEqual(disk_xml - configured_xml, EXPECTED_EXTRA_XML)

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

            for name in inventory.generated_feed_files:
                destination = root / "feeds" / name
                shutil.copyfile(REPO_ROOT / "feeds" / name, destination)
                tree = ET.parse(destination)
                channel = tree.getroot().find("channel")
                self.assertIsNotNone(channel)
                links = [
                    element
                    for element in channel.findall(ATOM_LINK)
                    if element.get("rel") == "self"
                ]
                self.assertEqual(len(links), 1, name)
                links[0].set(
                    "href",
                    f"{CANONICAL_FEED_BASE_URL}/feeds/{name}",
                )
                tree.write(
                    destination,
                    encoding="utf-8",
                    xml_declaration=True,
                )

            for name in inventory.generated_history_files:
                shutil.copyfile(
                    REPO_ROOT / "history" / name,
                    root / "history" / name,
                )

            sources = json.loads(
                (root / "config" / "sources_config.json").read_text(
                    encoding="utf-8"
                )
            )["sources"]
            with patch.dict(
                os.environ,
                {"FEED_BASE_URL": CANONICAL_FEED_BASE_URL},
                clear=False,
            ):
                save_opml(
                    generate_opml(sources),
                    root / "feeds" / "feeds.opml",
                )

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

            self.assertEqual(report.generated_feeds, 107)
            self.assertEqual(manifest["counts"]["objects"], 215)
            self.assertEqual(manifest["counts"]["routes"], 108)
            self.assertTrue((snapshot / "manifest.json").is_file())


if __name__ == "__main__":
    unittest.main()
