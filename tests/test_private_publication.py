from __future__ import annotations

import copy
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET

from scripts.build_snapshot_manifest import build_snapshot
from scripts.hydrate_private_state import hydrate_private_state
from scripts.private_feed_common import (
    CANONICAL_FEED_BASE_URL,
    BootstrapRequired,
    CanaryError,
    ManifestError,
    StorageOperationError,
    canonical_json_bytes,
    load_publication_policy,
    sha256_bytes,
)
from scripts.publish_snapshot import (
    ConcurrentPublicationError,
    apply_retention,
    publish_snapshot,
)
from scripts.rollback_snapshot import rollback_snapshot
from scripts.validate_snapshot import (
    SnapshotValidationError,
    validate_snapshot_directory,
    validate_working_state,
)
from tests.private_publication_helpers import (
    FakeObjectStore,
    competitor_pointer,
    create_test_repository,
    current_run_id,
    write_feed,
)


class PrivatePublicationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.sources = create_test_repository(self.root)
        self.state = self.root / ".private-feed-state"
        self.build = self.root / ".private-feed-build"
        self.store = FakeObjectStore()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def stage(self, run_id: str, *, mode: str = "pilot") -> Path:
        snapshot, _ = build_snapshot(
            repo_root=self.root,
            output_root=self.build,
            feed_base_url=CANONICAL_FEED_BASE_URL,
            mode=mode,
            pilot_feed_file=(
                "plain_feed.xml" if mode == "pilot" else None
            ),
            canary_feed_file="plain_feed.xml",
            baseline_dir=(
                self.state / "baseline"
                if (self.state / "baseline").exists()
                else None
            ),
            state_dir=self.state,
            run_id=run_id,
            revision="test-revision",
        )
        return snapshot

    def publish(self, snapshot: Path, *, canary=lambda manifest: None):
        return publish_snapshot(
            store=self.store,
            repo_root=self.root,
            snapshot_dir=snapshot,
            state_dir=self.state,
            feed_base_url=CANONICAL_FEED_BASE_URL,
            mode="pilot",
            pilot_feed_file="plain_feed.xml",
            retention=28,
            canary_runner=canary,
        )

    def bootstrap(self) -> None:
        hydrate_private_state(
            store=self.store,
            repo_root=self.root,
            state_dir=self.state,
            allow_bootstrap_from_local=True,
        )

    def publish_first(self, run_id: str = "run-01") -> Path:
        self.bootstrap()
        snapshot = self.stage(run_id)
        self.publish(snapshot)
        return snapshot

    def prepare_next(self, run_id: str) -> Path:
        hydrate_private_state(
            store=self.store,
            repo_root=self.root,
            state_dir=self.state,
            allow_bootstrap_from_local=False,
        )
        return self.stage(run_id)

    def test_bootstrap_requires_explicit_authorization_and_writes_no_remote_data(
        self,
    ) -> None:
        with self.assertRaises(BootstrapRequired):
            hydrate_private_state(
                store=self.store,
                repo_root=self.root,
                state_dir=self.state,
                allow_bootstrap_from_local=False,
            )
        self.assertEqual(self.store.objects, {})

        result = hydrate_private_state(
            store=self.store,
            repo_root=self.root,
            state_dir=self.state,
            allow_bootstrap_from_local=True,
        )
        self.assertEqual(result["status"], "bootstrap")
        self.assertTrue(
            (self.state / "baseline" / "feeds" / "plain_feed.xml").is_file()
        )
        self.assertEqual(self.store.objects, {})

    def test_hydration_rejects_hash_divergence_before_replacing_local_files(
        self,
    ) -> None:
        self.publish_first()
        local_feed = self.root / "feeds" / "plain_feed.xml"
        local_feed.write_bytes(b"local sentinel")
        key = "snapshots/run-01/feeds/plain_feed.xml"
        original = self.store.objects[key]
        self.store.direct_put(
            key,
            b"corrupt remote bytes",
            content_type=original.content_type,
            metadata=original.metadata,
        )

        with self.assertRaises(ManifestError):
            hydrate_private_state(
                store=self.store,
                repo_root=self.root,
                state_dir=self.state,
                allow_bootstrap_from_local=False,
            )
        self.assertEqual(local_feed.read_bytes(), b"local sentinel")

    def test_interrupted_upload_never_activates_current_pointer(self) -> None:
        self.bootstrap()
        snapshot = self.stage("run-interrupted")
        self.store.fail_on_put_number = 3

        with self.assertRaises(StorageOperationError):
            self.publish(snapshot)
        self.assertIsNone(current_run_id(self.store))
        self.assertNotIn("current.json", self.store.objects)

    def test_failed_post_activation_canary_restores_previous_pointer(self) -> None:
        self.publish_first("run-good")
        snapshot = self.prepare_next("run-bad")

        def canary(manifest):
            if manifest["run_id"] == "run-bad":
                raise RuntimeError("injected canary failure")

        with self.assertRaises(CanaryError):
            self.publish(snapshot, canary=canary)
        self.assertEqual(current_run_id(self.store), "run-good")

    def test_pointer_change_before_activation_stops_concurrent_publication(
        self,
    ) -> None:
        self.bootstrap()
        snapshot = self.stage("run-racing")
        self.store.current_gets = 0

        def inject_competitor(store: FakeObjectStore, count: int) -> None:
            if count == 2:
                body = competitor_pointer()
                store.direct_put("current.json", body)

        self.store.on_current_get = inject_competitor
        with self.assertRaises(ConcurrentPublicationError):
            self.publish(snapshot)
        self.assertEqual(current_run_id(self.store), "competing-run")

    def test_manual_rollback_validates_and_switches_only_the_pointer(self) -> None:
        self.publish_first("run-one")
        second = self.prepare_next("run-two")
        self.publish(second)
        before_objects = {
            key: value.data
            for key, value in self.store.objects.items()
            if key.startswith("snapshots/")
        }

        result = rollback_snapshot(
            store=self.store,
            repo_root=self.root,
            target_run_id="run-one",
            required_mode="pilot",
            feed_base_url=CANONICAL_FEED_BASE_URL,
            canary_runner=lambda manifest: None,
        )
        self.assertEqual(result["status"], "rolled-back")
        self.assertEqual(current_run_id(self.store), "run-one")
        after_objects = {
            key: value.data
            for key, value in self.store.objects.items()
            if key.startswith("snapshots/")
        }
        self.assertEqual(before_objects, after_objects)

    def test_failed_manual_rollback_canary_restores_original_pointer(self) -> None:
        self.publish_first("run-one")
        second = self.prepare_next("run-two")
        self.publish(second)

        def canary(manifest):
            if manifest["run_id"] == "run-one":
                raise RuntimeError("injected target failure")

        with self.assertRaises(CanaryError):
            rollback_snapshot(
                store=self.store,
                repo_root=self.root,
                target_run_id="run-one",
                required_mode="pilot",
                feed_base_url=CANONICAL_FEED_BASE_URL,
                canary_runner=canary,
            )
        self.assertEqual(current_run_id(self.store), "run-two")

    def test_manual_rollback_rejects_semantically_invalid_snapshot(self) -> None:
        self.publish_first("run-one")
        second = self.prepare_next("run-two")
        self.publish(second)

        feed_key = "snapshots/run-one/feeds/plain_feed.xml"
        manifest_key = "snapshots/run-one/manifest.json"
        invalid_feed = b"not an RSS document"
        original_feed = self.store.objects[feed_key]
        self.store.direct_put(
            feed_key,
            invalid_feed,
            content_type=original_feed.content_type,
            metadata={"sha256": sha256_bytes(invalid_feed)},
        )
        manifest = json.loads(
            self.store.objects[manifest_key].data.decode("utf-8")
        )
        manifest["objects"]["feeds/plain_feed.xml"]["size"] = len(invalid_feed)
        manifest["objects"]["feeds/plain_feed.xml"]["sha256"] = sha256_bytes(
            invalid_feed
        )
        manifest_bytes = canonical_json_bytes(manifest)
        self.store.direct_put(
            manifest_key,
            manifest_bytes,
            content_type="application/json; charset=utf-8",
            metadata={"sha256": sha256_bytes(manifest_bytes)},
        )

        with self.assertRaisesRegex(
            SnapshotValidationError,
            "RSS XML is not well formed",
        ):
            rollback_snapshot(
                store=self.store,
                repo_root=self.root,
                target_run_id="run-one",
                required_mode="pilot",
                feed_base_url=CANONICAL_FEED_BASE_URL,
                canary_runner=lambda manifest: None,
            )
        self.assertEqual(current_run_id(self.store), "run-two")

    def test_already_active_rollback_rechecks_current_pointer(self) -> None:
        self.publish_first("run-one")
        self.store.current_gets = 0

        def inject_competitor(store: FakeObjectStore, count: int) -> None:
            if count == 2:
                store.direct_put("current.json", competitor_pointer())

        self.store.on_current_get = inject_competitor
        with self.assertRaises(ConcurrentPublicationError):
            rollback_snapshot(
                store=self.store,
                repo_root=self.root,
                target_run_id="run-one",
                required_mode="pilot",
                feed_base_url=CANONICAL_FEED_BASE_URL,
                canary_runner=lambda manifest: None,
            )
        self.assertEqual(current_run_id(self.store), "competing-run")

    def test_retention_keeps_28_snapshots_including_active_and_previous(
        self,
    ) -> None:
        self.publish_first("run-00")
        for index in range(1, 30):
            snapshot = self.prepare_next(f"run-{index:02d}")
            self.publish(snapshot)

        run_ids = {
            key.split("/")[1]
            for key in self.store.objects
            if key.startswith("snapshots/") and key.endswith("/manifest.json")
        }
        self.assertEqual(len(run_ids), 28)
        self.assertIn("run-29", run_ids)
        self.assertIn("run-28", run_ids)
        self.assertNotIn("run-00", run_ids)
        self.assertNotIn("run-01", run_ids)

    def test_retention_verifies_that_deleted_prefix_is_empty(self) -> None:
        self.publish_first("run-00")
        for index in range(1, 3):
            snapshot = self.prepare_next(f"run-{index:02d}")
            self.publish(snapshot)

        current = self.store.objects["current.json"]
        with (
            patch.object(self.store, "delete_keys", return_value=None),
            self.assertRaisesRegex(
                StorageOperationError,
                "complete snapshot prefix",
            ),
        ):
            apply_retention(
                store=self.store,
                active_run_id="run-02",
                previous_run_id="run-01",
                keep=2,
                policy=load_publication_policy(self.root),
                expected_current_etag=current.etag,
            )

    def test_validator_accepts_duplicate_identical_guids_and_native_opml_url(
        self,
    ) -> None:
        report = validate_working_state(
            repo_root=self.root,
            feed_base_url=CANONICAL_FEED_BASE_URL,
            mode="full",
            pilot_feed_file=None,
            baseline_dir=None,
        )
        self.assertEqual(report.generated_feeds, 3)
        opml = (self.root / "feeds" / "feeds.opml").read_text(
            encoding="utf-8"
        )
        self.assertIn("https://native.example/feed.xml", opml)
        self.assertNotIn(
            f"{CANONICAL_FEED_BASE_URL}/feeds/native_feed.xml",
            opml,
        )

    def test_validator_blocks_content_downgrade_and_secret_leak(self) -> None:
        baseline = self.root / "baseline"
        baseline_feed = baseline / "feeds" / "linkedin_feed.xml"
        baseline_feed.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(
            self.root / "feeds" / "linkedin_feed.xml",
            baseline_feed,
        )
        write_feed(
            self.root / "feeds" / "linkedin_feed.xml",
            self_url=(
                f"{CANONICAL_FEED_BASE_URL}/feeds/linkedin_feed.xml"
            ),
            article_url="https://publisher.example/article-1",
            description="<p>curto</p>",
        )
        with self.assertRaisesRegex(
            SnapshotValidationError,
            "lost substantial content",
        ):
            validate_working_state(
                repo_root=self.root,
                feed_base_url=CANONICAL_FEED_BASE_URL,
                mode="pilot",
                pilot_feed_file="plain_feed.xml",
                baseline_dir=baseline,
            )

        write_feed(
            self.root / "feeds" / "linkedin_feed.xml",
            self_url=(
                f"{CANONICAL_FEED_BASE_URL}/feeds/linkedin_feed.xml"
            ),
            article_url="https://publisher.example/article-1",
            description="<p>the-secret-value</p>",
        )
        with self.assertRaisesRegex(
            SnapshotValidationError,
            "configured secret value",
        ):
            validate_working_state(
                repo_root=self.root,
                feed_base_url=CANONICAL_FEED_BASE_URL,
                mode="pilot",
                pilot_feed_file="plain_feed.xml",
                baseline_dir=None,
                secret_values=(b"the-secret-value",),
            )

    def test_validator_matches_tracking_variants_for_downgrade_checks(self) -> None:
        baseline = self.root / "baseline"
        baseline_feed = baseline / "feeds" / "linkedin_feed.xml"
        write_feed(
            baseline_feed,
            self_url="https://baseline.invalid/feeds/linkedin_feed.xml",
            article_url="https://publisher.example/article-1?utm_source=old",
            description=f"<p>{'conteudo completo ' * 90}</p>",
        )
        write_feed(
            self.root / "feeds" / "linkedin_feed.xml",
            self_url=(
                f"{CANONICAL_FEED_BASE_URL}/feeds/linkedin_feed.xml"
            ),
            article_url="https://publisher.example/article-1?trk=new",
            description="<p>curto</p>",
        )

        with self.assertRaisesRegex(
            SnapshotValidationError,
            "lost substantial content",
        ):
            validate_working_state(
                repo_root=self.root,
                feed_base_url=CANONICAL_FEED_BASE_URL,
                mode="pilot",
                pilot_feed_file="plain_feed.xml",
                baseline_dir=baseline,
            )

    def test_validator_preserves_identity_query_parameters(self) -> None:
        baseline = self.root / "baseline"
        baseline_feed = baseline / "feeds" / "plain_feed.xml"
        current_feed = self.root / "feeds" / "plain_feed.xml"
        first_url = "https://www.youtube.com/watch?v=first"
        second_url = "https://www.youtube.com/watch?v=second"
        write_feed(
            baseline_feed,
            self_url="https://baseline.invalid/feeds/plain_feed.xml",
            article_url=first_url,
            description="<p>primeiro</p>",
        )
        write_feed(
            current_feed,
            self_url=f"{CANONICAL_FEED_BASE_URL}/feeds/plain_feed.xml",
            article_url=first_url,
            description="<p>primeiro</p>",
        )

        for feed_path in (baseline_feed, current_feed):
            tree = ET.parse(feed_path)
            channel = tree.getroot().find("channel")
            assert channel is not None
            first_item = channel.find("item")
            assert first_item is not None
            second_item = copy.deepcopy(first_item)
            second_item.find("title").text = "Segundo vídeo"
            second_item.find("link").text = second_url
            second_item.find("guid").text = second_url
            channel.append(second_item)
            tree.write(feed_path, encoding="utf-8", xml_declaration=True)

        validate_working_state(
            repo_root=self.root,
            feed_base_url=CANONICAL_FEED_BASE_URL,
            mode="pilot",
            pilot_feed_file="plain_feed.xml",
            baseline_dir=baseline,
        )

    def test_validator_rejects_symlinked_artifact(self) -> None:
        target = self.root / "feed-target.xml"
        target.write_bytes(
            (self.root / "feeds" / "plain_feed.xml").read_bytes()
        )
        feed = self.root / "feeds" / "plain_feed.xml"
        feed.unlink()
        feed.symlink_to(target)

        with self.assertRaisesRegex(
            SnapshotValidationError,
            "symbolic link",
        ):
            validate_working_state(
                repo_root=self.root,
                feed_base_url=CANONICAL_FEED_BASE_URL,
                mode="pilot",
                pilot_feed_file="plain_feed.xml",
                baseline_dir=None,
            )

    def test_snapshot_rejects_non_allowlisted_extra_file(self) -> None:
        self.bootstrap()
        snapshot = self.stage("run-extra")
        (snapshot / "feeds" / "orphan_feed.xml").write_text(
            "not allowlisted",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(
            SnapshotValidationError,
            "non-allowlisted",
        ):
            validate_snapshot_directory(
                repo_root=self.root,
                snapshot_dir=snapshot,
                feed_base_url=CANONICAL_FEED_BASE_URL,
                mode="pilot",
                pilot_feed_file="plain_feed.xml",
            )

    def test_snapshot_rejects_content_type_outside_allowlist(self) -> None:
        self.bootstrap()
        snapshot = self.stage("run-content-type")
        manifest_path = snapshot / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["objects"]["feeds/plain_feed.xml"]["content_type"] = (
            "text/html; charset=utf-8"
        )
        manifest_path.write_bytes(canonical_json_bytes(manifest))

        with self.assertRaisesRegex(
            SnapshotValidationError,
            "content type differs from allowlist",
        ):
            validate_snapshot_directory(
                repo_root=self.root,
                snapshot_dir=snapshot,
                feed_base_url=CANONICAL_FEED_BASE_URL,
                mode="pilot",
                pilot_feed_file="plain_feed.xml",
            )

    def test_full_publication_rejects_temporary_or_legacy_origins(
        self,
    ) -> None:
        for origin in (
            "https://pilot.example.workers.dev",
            "https://feeds.fehla.xyz",
            "https://paulofeh.github.io/rss-de-valor",
        ):
            with self.subTest(origin=origin):
                with self.assertRaises(SnapshotValidationError):
                    validate_working_state(
                        repo_root=self.root,
                        feed_base_url=origin,
                        mode="full",
                        pilot_feed_file=None,
                        baseline_dir=None,
                    )

    def test_pilot_accepts_workers_dev_but_never_fehla_xyz(self) -> None:
        pilot_origin = "https://rss-de-valor.example.workers.dev"
        for source in self.sources:
            if source["scraper"] == "ExistingRssScraper":
                continue
            write_feed(
                self.root / "feeds" / source["feed_file"],
                self_url=f"{pilot_origin}/feeds/{source['feed_file']}",
                article_url=(
                    "https://publisher.example/"
                    f"{source['feed_file']}-article"
                ),
                description=f"<p>{'conteudo ' * 90}</p>",
            )
        original = os.environ.get("FEED_BASE_URL")
        try:
            os.environ["FEED_BASE_URL"] = pilot_origin
            from src.utils import generate_opml, save_opml

            save_opml(generate_opml(self.sources), self.root / "feeds" / "feeds.opml")
        finally:
            if original is None:
                os.environ.pop("FEED_BASE_URL", None)
            else:
                os.environ["FEED_BASE_URL"] = original

        report = validate_working_state(
            repo_root=self.root,
            feed_base_url=pilot_origin,
            mode="pilot",
            pilot_feed_file="plain_feed.xml",
            baseline_dir=None,
            production=False,
        )
        self.assertEqual(report.generated_feeds, 3)

        with self.assertRaises(SnapshotValidationError):
            validate_working_state(
                repo_root=self.root,
                feed_base_url="https://feeds.fehla.xyz",
                mode="pilot",
                pilot_feed_file="plain_feed.xml",
                baseline_dir=None,
                production=False,
            )


class ExistingPipelineSafetyTest(unittest.TestCase):
    def test_scraper_failure_does_not_replace_previous_feed_or_history(
        self,
    ) -> None:
        import main as scraper_main

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "config").mkdir()
            (root / "feeds").mkdir()
            (root / "history").mkdir()
            source = {
                "name": "Fonte com falha",
                "url": "https://publisher.example/source",
                "scraper": "FailingScraper",
                "feed_file": "preserved_feed.xml",
                "history_file": "preserved_history.json",
                "group": "outros",
            }
            (root / "config" / "sources_config.json").write_text(
                json.dumps({"sources": [source]}),
                encoding="utf-8",
            )
            feed = root / "feeds" / source["feed_file"]
            history = root / "history" / source["history_file"]
            feed.write_bytes(b"previous feed bytes")
            history.write_bytes(b'{"last_article_link":"previous"}')

            class FailingScraper:
                def __init__(self, url):
                    self.url = url

                def get_articles(self):
                    raise RuntimeError("injected scraper failure")

            previous_cwd = Path.cwd()
            try:
                os.chdir(root)
                with (
                    patch.object(
                        scraper_main,
                        "get_scraper_class",
                        return_value=FailingScraper,
                    ),
                    patch.object(scraper_main.time, "sleep"),
                    patch("builtins.print"),
                ):
                    scraper_main.main()
            finally:
                os.chdir(previous_cwd)

            self.assertEqual(feed.read_bytes(), b"previous feed bytes")
            self.assertEqual(
                history.read_bytes(),
                b'{"last_article_link":"previous"}',
            )


if __name__ == "__main__":
    unittest.main()
