from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.private_feed_common import (
    CANONICAL_FEED_BASE_URL,
    ConfigurationError,
)
from scripts.repair_martin_wolf_pubdate import (
    ARTICLE_URL,
    BASELINE_PUBDATE,
    CURRENT_PUBDATE,
    FEED_FILE,
    PROFILE_NAME,
    approved_pubdate_repair,
)
from scripts.validate_snapshot import (
    SnapshotValidationError,
    validate_working_state,
)
from tests.private_publication_helpers import (
    create_test_repository,
    write_feed,
    write_opml,
)


class MartinWolfPubdateRepairTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.sources = create_test_repository(self.root)
        source = next(
            item for item in self.sources if item["name"] == "Folha teste"
        )
        old_feed_file = source["feed_file"]
        old_history_file = source["history_file"]
        source.update(
            {
                "name": "Martin Wolf",
                "url": (
                    "https://feeds.folha.uol.com.br/colunas/"
                    "martinwolf/rss091.xml"
                ),
                "scraper": "FolhaRssFullContentScraper",
                "feed_file": FEED_FILE,
                "history_file": "martin_wolf_history.json",
                "group": "folha",
            }
        )
        (self.root / "feeds" / old_feed_file).rename(
            self.root / "feeds" / FEED_FILE
        )
        (self.root / "history" / old_history_file).rename(
            self.root / "history" / "martin_wolf_history.json"
        )
        (self.root / "config" / "sources_config.json").write_text(
            json.dumps({"sources": self.sources}, ensure_ascii=False),
            encoding="utf-8",
        )
        write_opml(self.root / "feeds" / "feeds.opml", self.sources)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _write_transition(
        self,
        *,
        article_url: str = ARTICLE_URL,
        current_pubdate: str = CURRENT_PUBDATE,
    ) -> Path:
        baseline = self.root / "baseline"
        write_feed(
            baseline / "feeds" / FEED_FILE,
            self_url=f"https://baseline.invalid/feeds/{FEED_FILE}",
            article_url=article_url,
            description="<p>stub conhecido</p>",
            author="Autor não encontrado",
            pubdate=BASELINE_PUBDATE,
        )
        write_feed(
            self.root / "feeds" / FEED_FILE,
            self_url=f"{CANONICAL_FEED_BASE_URL}/feeds/{FEED_FILE}",
            article_url=article_url,
            description=f"<p>{'conteúdo completo ' * 40}</p>",
            author="Martin Wolf",
            pubdate=current_pubdate,
        )
        return baseline

    def test_profile_resolves_only_the_expected_source(self) -> None:
        repair = approved_pubdate_repair(
            repo_root=self.root,
            profile=PROFILE_NAME,
        )

        self.assertEqual(repair.feed_file, FEED_FILE)
        self.assertEqual(repair.article_url, ARTICLE_URL)
        self.assertEqual(repair.baseline_pubdate, BASELINE_PUBDATE)
        self.assertEqual(repair.current_pubdate, CURRENT_PUBDATE)

        with self.assertRaisesRegex(
            ConfigurationError,
            "unsupported Martin Wolf publication-date repair profile",
        ):
            approved_pubdate_repair(
                repo_root=self.root,
                profile="unexpected-profile",
            )

    def test_profile_rejects_source_configuration_drift(self) -> None:
        self.sources[
            next(
                index
                for index, source in enumerate(self.sources)
                if source["name"] == "Martin Wolf"
            )
        ]["url"] = "https://publisher.example/unexpected"
        (self.root / "config" / "sources_config.json").write_text(
            json.dumps({"sources": self.sources}, ensure_ascii=False),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(
            ConfigurationError,
            "Martin Wolf publication-date repair source diverged",
        ):
            approved_pubdate_repair(
                repo_root=self.root,
                profile=PROFILE_NAME,
            )

    def test_validator_allows_only_the_exact_transition(self) -> None:
        baseline = self._write_transition()

        with self.assertRaisesRegex(
            SnapshotValidationError,
            "changed its publication date",
        ):
            validate_working_state(
                repo_root=self.root,
                feed_base_url=CANONICAL_FEED_BASE_URL,
                mode="full",
                pilot_feed_file=None,
                baseline_dir=baseline,
            )

        validate_working_state(
            repo_root=self.root,
            feed_base_url=CANONICAL_FEED_BASE_URL,
            mode="full",
            pilot_feed_file=None,
            baseline_dir=baseline,
            baseline_repair_profile=PROFILE_NAME,
        )

    def test_validator_rejects_a_different_article(self) -> None:
        baseline = self._write_transition(
            article_url="https://www1.folha.uol.com.br/colunas/martinwolf/"
            "2026/07/outro-artigo.shtml"
        )

        with self.assertRaisesRegex(
            SnapshotValidationError,
            "approved publication-date repair was not observed",
        ):
            validate_working_state(
                repo_root=self.root,
                feed_base_url=CANONICAL_FEED_BASE_URL,
                mode="full",
                pilot_feed_file=None,
                baseline_dir=baseline,
                baseline_repair_profile=PROFILE_NAME,
            )

    def test_validator_rejects_a_different_current_date(self) -> None:
        baseline = self._write_transition(
            current_pubdate="Wed, 22 Jul 2026 23:31:00 +0000"
        )

        with self.assertRaisesRegex(
            SnapshotValidationError,
            "approved publication-date repair was not observed",
        ):
            validate_working_state(
                repo_root=self.root,
                feed_base_url=CANONICAL_FEED_BASE_URL,
                mode="full",
                pilot_feed_file=None,
                baseline_dir=baseline,
                baseline_repair_profile=PROFILE_NAME,
            )

    def test_validator_rejects_a_different_baseline_date(self) -> None:
        baseline = self._write_transition()
        write_feed(
            baseline / "feeds" / FEED_FILE,
            self_url=f"https://baseline.invalid/feeds/{FEED_FILE}",
            article_url=ARTICLE_URL,
            description="<p>stub conhecido</p>",
            author="Autor não encontrado",
            pubdate="Wed, 22 Jul 2026 20:31:00 -0306",
        )

        with self.assertRaisesRegex(
            SnapshotValidationError,
            "approved publication-date repair was not observed",
        ):
            validate_working_state(
                repo_root=self.root,
                feed_base_url=CANONICAL_FEED_BASE_URL,
                mode="full",
                pilot_feed_file=None,
                baseline_dir=baseline,
                baseline_repair_profile=PROFILE_NAME,
            )


if __name__ == "__main__":
    unittest.main()
