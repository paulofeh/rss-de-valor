from __future__ import annotations

import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class PrivateWorkflowTest(unittest.TestCase):
    def test_pilot_and_rollback_share_concurrency_and_read_only_permission(
        self,
    ) -> None:
        pilot = (
            REPO_ROOT / ".github" / "workflows" / "private-feed-pilot.yml"
        ).read_text(encoding="utf-8")
        rollback = (
            REPO_ROOT / ".github" / "workflows" / "private-feed-rollback.yml"
        ).read_text(encoding="utf-8")
        for content in (pilot, rollback):
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
        self.assertIn(
            "FEED_BASE_URL: ${{ vars.PRIVATE_FEED_PILOT_ENDPOINT }}",
            pilot,
        )
        self.assertNotIn("git push", pilot)
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
