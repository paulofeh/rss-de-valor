from __future__ import annotations

import datetime
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytz

from main import CONTENT_PRESERVATION_LIMITS
from src.scrapers import ValorOGloboScraper
from src.utils import merge_articles_with_existing_feed
from tests.private_publication_helpers import write_feed


ARTICLE_URL = (
    "https://oglobo.globo.com/blogs/malu-gaspar/post/2026/07/"
    "artigo-de-teste.ghtml"
)
PREVIOUS_ARTICLE_URL = (
    "https://oglobo.globo.com/blogs/malu-gaspar/post/2026/07/"
    "artigo-anterior.ghtml"
)
LISTING_HTML = f"""
<div class="bastian-feed-item">
  <a href="{ARTICLE_URL}">
    <h2 class="feed-post-link">Artigo de teste</h2>
  </a>
  <span class="feed-post-datetime">25/07/2026 10:00</span>
  <span class="feed-post-metadata-section">Malu Gaspar</span>
  <p class="feed-post-body-resumo">Resumo da listagem</p>
</div>
""".encode()


class ValorOGloboNonDegradationTest(unittest.TestCase):
    def scrape_with_content(self, content: str | None) -> dict:
        response = MagicMock()
        response.content = LISTING_HTML
        session = MagicMock()
        session.get.return_value = response
        scraper = ValorOGloboScraper(
            "https://oglobo.globo.com/blogs/malu-gaspar/"
        )

        with (
            patch(
                "src.scrapers.requests_retry_session",
                return_value=session,
            ),
            patch.object(
                scraper,
                "_fetch_article_content",
                return_value=content,
            ),
        ):
            articles = scraper.get_articles(limit=1)

        self.assertEqual(len(articles), 1)
        response.raise_for_status.assert_called_once_with()
        return articles[0]

    def test_full_article_marks_enrichment_as_successful(self) -> None:
        article = self.scrape_with_content("<p>Conteúdo integral</p>")

        self.assertEqual(article["description"], "<p>Conteúdo integral</p>")
        self.assertIs(article["_enrichment_failed"], False)

    def test_missing_full_article_marks_enrichment_as_failed(self) -> None:
        article = self.scrape_with_content(None)

        self.assertEqual(article["description"], "Resumo da listagem")
        self.assertIs(article["_enrichment_failed"], True)

    def test_known_failed_article_reuses_previous_complete_item(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="rss-valor-oglobo-preservation-"
        ) as temporary:
            feed_path = Path(temporary) / "feeds" / "malu.xml"
            write_feed(
                feed_path,
                self_url="https://feeds.example/feeds/malu.xml",
                article_url=ARTICLE_URL,
                description="<p>Conteúdo integral anterior</p>",
                author="Malu Gaspar",
            )
            incoming = {
                "title": "Artigo de teste",
                "link": ARTICLE_URL,
                "pubdate": datetime.datetime.now(pytz.UTC),
                "author": "Malu Gaspar",
                "description": "Resumo da listagem",
                "_enrichment_failed": True,
            }

            with patch(
                "src.utils.get_feed_path",
                return_value=str(feed_path),
            ):
                merged = merge_articles_with_existing_feed(
                    [incoming],
                    "malu.xml",
                    limit=10,
                )

        self.assertEqual(len(merged), 1)
        self.assertEqual(
            merged[0]["description"],
            "<p>Conteúdo integral anterior</p>",
        )
        self.assertEqual(merged[0]["author"], "Malu Gaspar")

    def test_new_failed_article_is_deferred_and_previous_feed_is_refilled(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(
            prefix="rss-valor-oglobo-deferral-"
        ) as temporary:
            feed_path = Path(temporary) / "feeds" / "malu.xml"
            write_feed(
                feed_path,
                self_url="https://feeds.example/feeds/malu.xml",
                article_url=PREVIOUS_ARTICLE_URL,
                description="<p>Conteúdo anterior</p>",
                author="Malu Gaspar",
            )
            incoming = {
                "title": "Artigo novo incompleto",
                "link": ARTICLE_URL,
                "pubdate": datetime.datetime.now(pytz.UTC),
                "author": "Malu Gaspar",
                "description": "Somente o resumo",
                "_enrichment_failed": True,
            }

            with patch(
                "src.utils.get_feed_path",
                return_value=str(feed_path),
            ):
                merged = merge_articles_with_existing_feed(
                    [incoming],
                    "malu.xml",
                    limit=10,
                )

        self.assertEqual(
            [article["link"] for article in merged],
            [PREVIOUS_ARTICLE_URL],
        )
        self.assertEqual(merged[0]["description"], "<p>Conteúdo anterior</p>")

    def test_main_applies_preservation_to_valor_oglobo(self) -> None:
        self.assertEqual(
            CONTENT_PRESERVATION_LIMITS["ValorOGloboScraper"],
            10,
        )


if __name__ == "__main__":
    unittest.main()
