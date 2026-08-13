from __future__ import annotations

import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class PrivateWorkflowTest(unittest.TestCase):
    def test_private_workflows_share_concurrency_and_read_only_permission(
        self,
    ) -> None:
        pilot = (
            REPO_ROOT / ".github" / "workflows" / "private-feed-pilot.yml"
        ).read_text(encoding="utf-8")
        publication = (
            REPO_ROOT
            / ".github"
            / "workflows"
            / "private-feed-publication.yml"
        ).read_text(encoding="utf-8")
        rollback = (
            REPO_ROOT / ".github" / "workflows" / "private-feed-rollback.yml"
        ).read_text(encoding="utf-8")
        for content in (pilot, publication, rollback):
            self.assertIn("group: private-feed-r2-publication", content)
            self.assertIn("queue: max", content)
            self.assertIn("contents: read", content)
            self.assertNotIn("contents: write", content)
            self.assertIn(
                "actions/checkout@11d5960a326750d5838078e36cf38b85af677262",
                content,
            )
            self.assertIn(
                "actions/setup-python@a309ff8b426b58ec0e2a45f0f869d46889d02405",
                content,
            )
        self.assertIn("PRIVATE_FEED_PILOT_ENABLED == 'true'", pilot)
        self.assertNotIn(
            "github.event_name == 'workflow_dispatch' ||",
            pilot,
        )
        self.assertIn(
            "FEED_BASE_URL: ${{ vars.PRIVATE_FEED_PILOT_ENDPOINT }}",
            pilot,
        )
        self.assertIn("PRIVATE_FEED_FULL_ENABLED == 'true'", publication)
        self.assertIn("inputs.confirm_full_publication == true", publication)
        self.assertIn("repair_linkedin_baseline:", publication)
        self.assertIn("repair_martin_wolf_pubdate:", publication)
        self.assertIn("migrate_folha_juliano_sergio:", publication)
        self.assertIn("migrate_cnn_duda_herriot:", publication)
        self.assertIn("migrate_folha_caetano_w_galindo:", publication)
        self.assertIn(
            "inputs.repair_linkedin_baseline == true",
            publication,
        )
        self.assertIn(
            "inputs.repair_martin_wolf_pubdate == true",
            publication,
        )
        self.assertIn(
            "inputs.migrate_folha_juliano_sergio == true",
            publication,
        )
        self.assertIn(
            "inputs.migrate_cnn_duda_herriot == true",
            publication,
        )
        self.assertIn(
            "inputs.migrate_folha_caetano_w_galindo == true",
            publication,
        )
        self.assertIn(
            "BASELINE_REPAIR_PROFILE:",
            publication,
        )
        self.assertIn(
            "linkedin-full-content-2026-07-27",
            publication,
        )
        self.assertIn(
            "martin-wolf-pubdate-2026-07-27",
            publication,
        )
        self.assertIn(
            "--baseline-repair-profile",
            publication,
        )
        self.assertIn(
            "--missing-object-profile",
            publication,
        )
        self.assertIn(
            "folha-juliano-sergio-2026-07-27",
            publication,
        )
        self.assertIn(
            "cnn-duda-herriot-2026-08-12",
            publication,
        )
        self.assertIn(
            "folha-caetano-w-galindo-2026-08-13",
            publication,
        )
        self.assertIn(
            'if [[ -n "$BASELINE_REPAIR_PROFILE" ]]',
            publication,
        )
        self.assertIn(
            "FEED_BASE_URL: https://feeds.paulofehlauer.com",
            publication,
        )
        self.assertIn("--mode full", publication)
        self.assertIn("--canary-feed-file", publication)
        self.assertNotIn("--allow-bootstrap-from-local", publication)
        self.assertIn("--required-mode full", rollback)
        self.assertIn(
            "PRIVATE_FEED_ENDPOINT: https://feeds.paulofehlauer.com",
            rollback,
        )
        self.assertNotIn("git push", pilot)
        self.assertNotIn("git push", publication)
        self.assertNotIn("git push", rollback)

    def test_linkedin_repair_is_manual_and_wraps_hydration(self) -> None:
        publication = (
            REPO_ROOT
            / ".github"
            / "workflows"
            / "private-feed-publication.yml"
        ).read_text(encoding="utf-8")

        stage = publication.index(
            "Stage the approved LinkedIn repair baseline"
        )
        hydrate = publication.index("Hydrate the active private snapshot")
        restore = publication.index(
            "Restore the approved LinkedIn repair baseline"
        )
        generate = publication.index(
            "Generate feeds from the hydrated state"
        )

        self.assertLess(stage, hydrate)
        self.assertLess(hydrate, restore)
        self.assertLess(restore, generate)
        self.assertGreaterEqual(
            publication.count("github.event_name == 'workflow_dispatch'"),
            3,
        )
        self.assertEqual(
            publication.count(
                "python scripts/repair_linkedin_baseline.py"
            ),
            2,
        )

    def test_martin_wolf_pubdate_repair_is_manual_and_mutually_exclusive(
        self,
    ) -> None:
        publication = (
            REPO_ROOT
            / ".github"
            / "workflows"
            / "private-feed-publication.yml"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "Validate manual repair selection",
            publication,
        )
        self.assertIn("selected_profiles=0", publication)
        self.assertIn('"$MIGRATE_DUDA"', publication)
        self.assertIn('"$MIGRATE_CAETANO"', publication)
        self.assertIn("selected_profiles > 1", publication)
        self.assertIn(
            "repair and migration profiles are mutually exclusive",
            publication,
        )

    def test_public_workflow_and_generated_artifacts_are_retired(self) -> None:
        self.assertFalse(
            (REPO_ROOT / ".github" / "workflows" / "workflow.yml").exists()
        )
        gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("/feeds/", gitignore)
        self.assertIn("/history/", gitignore)


if __name__ == "__main__":
    unittest.main()
