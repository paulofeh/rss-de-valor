from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

from src.scrapers import CNNBrasilSectionScraper, get_scraper_class


REPO_ROOT = Path(__file__).resolve().parents[1]
CNN_AGRO_URL = "https://www.cnnbrasil.com.br/agro/"


def cnn_post(
    *,
    slug: str,
    title: str,
    category_slug: str = "agro",
    path_prefix: str = "agro",
) -> dict:
    return {
        "slug": slug,
        "title": title,
        "excerpt": f"Resumo de {title}",
        "permalink": (
            f"https://www.cnnbrasil.com.br/{path_prefix}/{slug}/"
        ),
        "publish_date": "2026-07-27 09:39:28",
        "author": {"list": [{"name": "Autora CNN"}]},
        "category": {
            "id": 78671,
            "name": "Agro",
            "slug": category_slug,
            "url": CNN_AGRO_URL,
        },
    }


def list_block(origin_slug: str, posts: list[dict]) -> dict:
    return {
        "block_type": "list",
        "data": {
            "details": {
                "settings": {
                    "posts_origin": {
                        "id": 78671,
                        "name": "Agro",
                        "slug": origin_slug,
                        "url": CNN_AGRO_URL,
                    },
                },
                "data": posts,
            },
        },
    }


def resolver_payload(*blocks: dict) -> dict:
    return {
        "data": {
            "home": {
                "title": "Agro",
                "slug": "agro",
                "url": CNN_AGRO_URL,
            },
            "sections": [
                {
                    "section_title": "Últimas Notícias",
                    "blocks": [[block] for block in blocks],
                },
            ],
        },
    }


class CNNBrasilSectionScraperTest(unittest.TestCase):
    def scrape(
        self,
        payload: dict,
        *,
        body: str = "<p>Conteúdo integral</p>",
    ) -> tuple[list[dict], CNNBrasilSectionScraper, MagicMock]:
        response = MagicMock()
        response.json.return_value = payload
        session = MagicMock()
        session.get.return_value = response
        scraper = CNNBrasilSectionScraper(CNN_AGRO_URL)

        with (
            patch(
                "src.scrapers.requests_retry_session",
                return_value=session,
            ),
            patch.object(
                scraper,
                "_fetch_full_content",
                return_value=body,
            ),
        ):
            articles = scraper.get_articles(limit=10)

        response.raise_for_status.assert_called_once_with()
        return articles, scraper, session

    def test_extracts_only_the_matching_section_list(self) -> None:
        correct = [
            cnn_post(slug="safra-recorde", title="Safra recorde"),
            cnn_post(slug="credito-rural", title="Crédito rural"),
        ]
        payload = resolver_payload(
            list_block(
                "politica",
                [
                    cnn_post(
                        slug="eleicao",
                        title="Eleição",
                        category_slug="politica",
                        path_prefix="politica",
                    )
                ],
            ),
            list_block("agro", correct),
        )

        articles, scraper, session = self.scrape(payload)

        self.assertEqual(
            [article["title"] for article in articles],
            ["Safra recorde", "Crédito rural"],
        )
        self.assertTrue(
            all(
                urlparse(article["link"]).path.startswith("/agro/")
                for article in articles
            )
        )
        self.assertTrue(
            all(
                article["description"] == "<p>Conteúdo integral</p>"
                for article in articles
            )
        )
        session.get.assert_called_once_with(
            scraper._resolver_url(),
            timeout=30,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36"
                ),
            },
        )

    def test_rejects_an_off_scope_post_in_the_matching_list(self) -> None:
        payload = resolver_payload(
            list_block(
                "agro",
                [
                    cnn_post(slug="safra-recorde", title="Safra recorde"),
                    cnn_post(
                        slug="eleicao",
                        title="Eleição",
                        category_slug="politica",
                        path_prefix="politica",
                    ),
                ],
            )
        )

        articles, _, _ = self.scrape(payload)

        self.assertEqual(articles, [])

    def test_fails_closed_without_a_matching_list(self) -> None:
        payload = resolver_payload(
            list_block(
                "politica",
                [
                    cnn_post(
                        slug="eleicao",
                        title="Eleição",
                        category_slug="politica",
                        path_prefix="politica",
                    )
                ],
            )
        )

        articles, _, _ = self.scrape(payload)

        self.assertEqual(articles, [])

    def test_registry_and_config_use_the_section_scraper(self) -> None:
        self.assertIs(
            get_scraper_class("CNNBrasilSectionScraper"),
            CNNBrasilSectionScraper,
        )
        config = json.loads(
            (REPO_ROOT / "config" / "sources_config.json").read_text(
                encoding="utf-8"
            )
        )
        source = next(
            item
            for item in config["sources"]
            if item["name"] == "CNN Agro"
        )
        self.assertEqual(source["scraper"], "CNNBrasilSectionScraper")

    def test_checked_in_feed_contains_only_agro_items(self) -> None:
        tree = ET.parse(REPO_ROOT / "feeds" / "cnn_agro_feed.xml")
        links = [
            element.text or ""
            for element in tree.getroot().findall("./channel/item/link")
        ]

        self.assertGreater(len(links), 0)
        self.assertTrue(
            all(
                urlparse(link).scheme == "https"
                and urlparse(link).netloc == "www.cnnbrasil.com.br"
                and urlparse(link).path.startswith("/agro/")
                for link in links
            )
        )


if __name__ == "__main__":
    unittest.main()
