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

    def test_existing_public_workflow_remains_present_and_independent(
        self,
    ) -> None:
        public = (
            REPO_ROOT / ".github" / "workflows" / "workflow.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("contents: write", public)
        self.assertIn("git push", public)
        self.assertNotIn("private-feed-r2-publication", public)


if __name__ == "__main__":
    unittest.main()
