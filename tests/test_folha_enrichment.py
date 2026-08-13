from __future__ import annotations

import datetime
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import MagicMock, patch

from main import CONTENT_PRESERVATION_LIMITS
from src.scrapers import FolhaRssFullContentScraper, FolhaScraper
from src.utils import load_sources_config


COLUMN_URL = "https://www1.folha.uol.com.br/colunas/giovana-madalosso/"
FIRST_URL = (
    "https://www1.folha.uol.com.br/colunas/giovana-madalosso/"
    "2026/07/primeiro-artigo.shtml"
)
SECOND_URL = (
    "https://www1.folha.uol.com.br/colunas/giovana-madalosso/"
    "2026/07/segundo-artigo.shtml"
)

LISTING_HTML = f"""
<div class="c-headline c-headline--opinion c-headline--opinion--especial">
  <a class="c-headline__url" href="{FIRST_URL}">
    <h2 class="c-headline__title">Primeiro artigo</h2>
    <p class="c-headline__standfirst">Resumo do primeiro artigo</p>
    <time class="c-headline__dateline" datetime="2026-07-25 23:00:00"></time>
  </a>
</div>
<div class="c-headline c-headline--newslist">
  <a class="c-headline__url" href="{SECOND_URL}">
    <h2 class="c-headline__title">Segundo artigo</h2>
    <p class="c-headline__standfirst">Resumo do segundo artigo</p>
    <time class="c-headline__dateline" datetime="2026-07-18 23:00:00"></time>
  </a>
</div>
<div class="c-headline c-headline--newslist">
  <a class="c-headline__url" href="{FIRST_URL}">
    <h2 class="c-headline__title">Primeiro artigo duplicado</h2>
    <time class="c-headline__dateline" datetime="2026-07-25 23:00:00"></time>
  </a>
</div>
<div class="c-headline c-headline--newslist">
  <a class="c-headline__url"
     href="https://www1.folha.uol.com.br/colunas/outra-coluna/2026/07/fora-do-escopo.shtml">
    <h2 class="c-headline__title">Artigo de outra coluna</h2>
    <time class="c-headline__dateline" datetime="2026-07-20 12:00:00"></time>
  </a>
</div>
""".encode()


class FolhaPageEnrichmentTest(unittest.TestCase):
    @staticmethod
    def _session_for_listing() -> tuple[MagicMock, MagicMock]:
        response = MagicMock()
        response.content = LISTING_HTML
        session = MagicMock()
        session.get.return_value = response
        return session, response

    def test_collects_deduplicates_and_enriches_multiple_articles(self) -> None:
        session, response = self._session_for_listing()
        scraper = FolhaScraper(COLUMN_URL)

        with (
            patch(
                "src.scrapers.requests_retry_session",
                return_value=session,
            ),
            patch.object(
                FolhaRssFullContentScraper,
                "_fetch_article_content",
                side_effect=[
                    "<p>Conteúdo integral do primeiro artigo</p>",
                    "<p>Conteúdo integral do segundo artigo</p>",
                ],
            ) as fetch_content,
        ):
            articles = scraper.get_articles(limit=10)

        self.assertEqual([article["link"] for article in articles], [
            FIRST_URL,
            SECOND_URL,
        ])
        self.assertEqual(
            [article["author"] for article in articles],
            ["Giovana Madalosso", "Giovana Madalosso"],
        )
        self.assertEqual(
            articles[0]["description"],
            "<p>Conteúdo integral do primeiro artigo</p>",
        )
        self.assertEqual(
            articles[1]["description"],
            "<p>Conteúdo integral do segundo artigo</p>",
        )
        self.assertTrue(all(
            article["_enrichment_failed"] is False
            for article in articles
        ))
        self.assertEqual(
            articles[0]["pubdate"].utcoffset(),
            datetime.timedelta(hours=-3),
        )
        self.assertEqual(fetch_content.call_count, 2)
        response.raise_for_status.assert_called_once_with()

    def test_failed_enrichment_keeps_summary_and_marks_article(self) -> None:
        session, _ = self._session_for_listing()
        scraper = FolhaScraper(COLUMN_URL)

        with (
            patch(
                "src.scrapers.requests_retry_session",
                return_value=session,
            ),
            patch.object(
                FolhaRssFullContentScraper,
                "_fetch_article_content",
                return_value=None,
            ),
        ):
            articles = scraper.get_articles(limit=1)

        self.assertEqual(len(articles), 1)
        self.assertEqual(
            articles[0]["description"],
            "Resumo do primeiro artigo",
        )
        self.assertIs(articles[0]["_enrichment_failed"], True)

    def test_main_preserves_complete_page_based_folha_items(self) -> None:
        self.assertEqual(
            CONTENT_PRESERVATION_LIMITS["FolhaScraper"],
            10,
        )


class FolhaRssConfigurationTest(unittest.TestCase):
    def test_caetano_w_galindo_uses_page_scraper_with_author_fallback(
        self,
    ) -> None:
        source = next(
            source
            for source in load_sources_config()
            if source["name"] == "Caetano W. Galindo"
        )

        self.assertEqual(
            source["url"],
            "https://www1.folha.uol.com.br/colunas/caetano-w-galindo/",
        )
        self.assertEqual(source["scraper"], "FolhaScraper")
        self.assertEqual(
            source["feed_file"],
            "caetano_w_galindo_feed.xml",
        )
        self.assertEqual(
            FolhaRssFullContentScraper._default_author_for_url(
                source["url"]
            ),
            "Caetano W. Galindo",
        )

    def test_juliano_spyer_uses_page_scraper_because_rss_is_stale(self) -> None:
        source = next(
            source
            for source in load_sources_config()
            if source["name"] == "Juliano Spyer"
        )

        self.assertEqual(
            source["url"],
            "https://www1.folha.uol.com.br/colunas/juliano-spyer/",
        )
        self.assertEqual(source["scraper"], "FolhaScraper")
        self.assertEqual(source["feed_file"], "juliano_spyer_feed.xml")

    def test_sergio_rodrigues_uses_native_rss_with_full_content(self) -> None:
        source = next(
            source
            for source in load_sources_config()
            if source["name"] == "Sérgio Rodrigues"
        )

        self.assertEqual(
            source["url"],
            (
                "https://feeds.folha.uol.com.br/colunas/"
                "sergio-rodrigues/rss091.xml"
            ),
        )
        self.assertEqual(source["scraper"], "FolhaRssFullContentScraper")
        self.assertEqual(source["feed_file"], "sergio_rodrigues_feed.xml")

    def test_sergio_rodrigues_rss_gets_author_fallback(self) -> None:
        item = ET.fromstring(
            """
            <item>
              <title>Artigo de teste</title>
              <link>https://www1.folha.uol.com.br/colunas/sergio-rodrigues/2026/07/artigo.shtml</link>
              <description>Resumo</description>
              <pubDate>Wed, 22 Jul 2026 23:43:00 +0000</pubDate>
            </item>
            """
        )
        scraper = FolhaRssFullContentScraper(
            (
                "https://feeds.folha.uol.com.br/colunas/"
                "sergio-rodrigues/rss091.xml"
            )
        )

        with patch.object(
            scraper,
            "_fetch_article_content",
            return_value="<p>Conteúdo integral</p>",
        ):
            article = scraper._parse_item(item)

        self.assertEqual(article["author"], "Sérgio Rodrigues")
        self.assertEqual(article["description"], "<p>Conteúdo integral</p>")
        self.assertIs(article["_enrichment_failed"], False)

    def test_martin_wolf_uses_native_rss_with_full_content(self) -> None:
        source = next(
            source
            for source in load_sources_config()
            if source["name"] == "Martin Wolf"
        )

        self.assertEqual(
            source["url"],
            "https://feeds.folha.uol.com.br/colunas/martinwolf/rss091.xml",
        )
        self.assertEqual(source["scraper"], "FolhaRssFullContentScraper")
        self.assertEqual(source["feed_file"], "martin_wolf_feed.xml")

    def test_martin_wolf_rss_gets_author_fallback(self) -> None:
        item = ET.fromstring(
            """
            <item>
              <title>Artigo de teste</title>
              <link>https://www1.folha.uol.com.br/colunas/martinwolf/2026/07/artigo.shtml</link>
              <description>Resumo</description>
              <pubDate>Wed, 22 Jul 2026 23:30:00 +0000</pubDate>
            </item>
            """
        )
        scraper = FolhaRssFullContentScraper(
            "https://feeds.folha.uol.com.br/colunas/martinwolf/rss091.xml"
        )

        with patch.object(
            scraper,
            "_fetch_article_content",
            return_value="<p>Conteúdo integral</p>",
        ):
            article = scraper._parse_item(item)

        self.assertEqual(article["author"], "Martin Wolf")
        self.assertEqual(article["description"], "<p>Conteúdo integral</p>")
        self.assertIs(article["_enrichment_failed"], False)


if __name__ == "__main__":
    unittest.main()
