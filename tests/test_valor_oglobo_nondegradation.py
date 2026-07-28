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
                "_fetch_article_enrichment",
                return_value={
                    "content": content,
                    "author": "Malu Gaspar",
                    "pubdate": datetime.datetime(
                        2026,
                        7,
                        25,
                        10,
                        0,
                        tzinfo=pytz.UTC,
                    ),
                },
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

    def test_successful_valor_enrichment_preserves_known_pubdate(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(
            prefix="rss-valor-pubdate-preservation-"
        ) as temporary:
            feed_path = Path(temporary) / "feeds" / "valor.xml"
            baseline_pubdate = datetime.datetime(
                2026,
                7,
                20,
                8,
                0,
                tzinfo=pytz.UTC,
            )
            write_feed(
                feed_path,
                self_url="https://feeds.example/feeds/valor.xml",
                article_url=ARTICLE_URL,
                description="<p>Resumo anterior</p>",
                author="Política",
                pubdate="Mon, 20 Jul 2026 08:00:00 +0000",
            )
            incoming = {
                "title": "Artigo de teste",
                "link": ARTICLE_URL,
                "pubdate": datetime.datetime(
                    2026,
                    7,
                    20,
                    10,
                    0,
                    tzinfo=pytz.UTC,
                ),
                "author": "Bruno Carazza",
                "description": "<p>Conteúdo integral novo</p>",
                "_enrichment_failed": False,
            }

            with patch(
                "src.utils.get_feed_path",
                return_value=str(feed_path),
            ):
                merged = merge_articles_with_existing_feed(
                    [incoming],
                    "valor.xml",
                    limit=10,
                    preserve_existing_pubdate=True,
                )

        self.assertEqual(merged[0]["pubdate"], baseline_pubdate)
        self.assertEqual(
            merged[0]["description"],
            "<p>Conteúdo integral novo</p>",
        )
        self.assertEqual(merged[0]["author"], "Bruno Carazza")

    def test_main_applies_preservation_to_valor_oglobo(self) -> None:
        self.assertEqual(
            CONTENT_PRESERVATION_LIMITS["ValorOGloboScraper"],
            10,
        )

    def test_valor_teaser_uses_official_amp_content_and_metadata(self) -> None:
        article_url = (
            "https://valor.globo.com/politica/coluna/"
            "artigo-de-teste.ghtml"
        )
        amp_url = (
            "https://valor.globo.com/google/amp/politica/coluna/"
            "artigo-de-teste.ghtml"
        )
        standard_response = MagicMock()
        standard_response.content = f"""
        <html>
          <head><link rel="amphtml" href="{amp_url}"></head>
          <body>
            <p class="top__signature__text__author-name">
              Por Bruno Carazza
            </p>
            <time datetime="2026-07-27T05:01:02.329-03:00"></time>
            <div class="mc-article-body">
              <div class="content-text">
                <p class="content-text__container">Somente o teaser.</p>
              </div>
            </div>
          </body>
        </html>
        """.encode()
        standard_response.raise_for_status = MagicMock()

        long_paragraph = "Texto integral do artigo " * 20
        amp_response = MagicMock()
        amp_response.content = f"""
        <section class="globo-amp-article-body piano">
          <section>
            <p>{long_paragraph}</p>
            <p>{long_paragraph}</p>
            <p>{long_paragraph}</p>
          </section>
          <div class="amp-barreira amp-barreira-piano">
            <section class="paywall-amp-section2">
              <p>Já possui conta? Faça Login</p>
            </section>
          </div>
        </section>
        """.encode()
        amp_response.raise_for_status = MagicMock()

        session = MagicMock()
        session.get.side_effect = [standard_response, amp_response]
        scraper = ValorOGloboScraper(
            "https://valor.globo.com/autores/bruno-carazza/"
        )

        with patch(
            "src.scrapers.requests_retry_session",
            return_value=session,
        ):
            enrichment = scraper._fetch_article_enrichment(article_url)

        self.assertIn("Texto integral do artigo", enrichment["content"])
        self.assertNotIn("Faça Login", enrichment["content"])
        self.assertEqual(enrichment["author"], "Bruno Carazza")
        self.assertEqual(
            enrichment["pubdate"].isoformat(),
            "2026-07-27T05:01:02.329000-03:00",
        )
        self.assertEqual(session.get.call_count, 2)

    def test_short_valor_content_without_amp_is_an_enrichment_failure(
        self,
    ) -> None:
        response = MagicMock()
        response.content = b"""
        <div class="mc-article-body">
          <div class="content-text">
            <p class="content-text__container">Somente o teaser.</p>
          </div>
        </div>
        """
        response.raise_for_status = MagicMock()
        session = MagicMock()
        session.get.return_value = response
        scraper = ValorOGloboScraper(
            "https://valor.globo.com/autores/bruno-carazza/"
        )

        with patch(
            "src.scrapers.requests_retry_session",
            return_value=session,
        ):
            enrichment = scraper._fetch_article_enrichment(
                "https://valor.globo.com/politica/coluna/teste.ghtml"
            )

        self.assertIsNone(enrichment["content"])
        self.assertEqual(session.get.call_count, 1)

    def test_short_oglobo_content_preserves_existing_behavior(self) -> None:
        response = MagicMock()
        response.content = b"""
        <div class="mc-article-body">
          <div class="content-text">
            <p class="content-text__container">Nota curta completa.</p>
          </div>
        </div>
        """
        response.raise_for_status = MagicMock()
        session = MagicMock()
        session.get.return_value = response
        scraper = ValorOGloboScraper(
            "https://oglobo.globo.com/blogs/malu-gaspar/"
        )

        with patch(
            "src.scrapers.requests_retry_session",
            return_value=session,
        ):
            enrichment = scraper._fetch_article_enrichment(
                "https://oglobo.globo.com/blogs/malu-gaspar/"
                "post/2026/07/nota-curta.ghtml"
            )

        self.assertIn("Nota curta completa", enrichment["content"])
        self.assertEqual(session.get.call_count, 1)

    def test_valor_column_source_overrides_section_as_author(self) -> None:
        listing = LISTING_HTML.replace(
            ARTICLE_URL.encode(),
            (
                b"https://valor.globo.com/politica/coluna/"
                b"artigo-de-teste.ghtml"
            ),
        ).replace(b"Malu Gaspar", b"Politica")
        response = MagicMock()
        response.content = listing
        response.raise_for_status = MagicMock()
        session = MagicMock()
        session.get.return_value = response
        scraper = ValorOGloboScraper(
            "https://valor.globo.com/autores/bruno-carazza/"
        )

        with (
            patch(
                "src.scrapers.requests_retry_session",
                return_value=session,
            ),
            patch.object(
                scraper,
                "_fetch_article_enrichment",
                return_value={
                    "content": "<p>" + ("Completo " * 150) + "</p>",
                    "author": "Política",
                    "pubdate": datetime.datetime(
                        2026,
                        7,
                        27,
                        5,
                        1,
                        tzinfo=pytz.UTC,
                    ),
                },
            ),
        ):
            articles = scraper.get_articles(limit=1)

        self.assertEqual(articles[0]["author"], "Bruno Carazza")


if __name__ == "__main__":
    unittest.main()
