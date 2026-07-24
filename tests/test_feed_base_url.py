from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET

from src.utils import (
    DEFAULT_FEED_BASE_URL,
    generate_opml,
    get_feed_base_url,
    get_feed_url,
    get_opml_url,
    get_source_feed_url,
    normalize_feed_self_link,
)
from tests.private_publication_helpers import write_feed


class FeedBaseUrlTest(unittest.TestCase):
    def test_default_preserves_existing_pages_urls(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(get_feed_base_url(), DEFAULT_FEED_BASE_URL)
            self.assertEqual(
                get_feed_url("example.xml"),
                (
                    "https://paulofeh.github.io/rss-de-valor/"
                    "feeds/example.xml"
                ),
            )
            self.assertEqual(
                get_opml_url(),
                (
                    "https://paulofeh.github.io/rss-de-valor/"
                    "feeds/feeds.opml"
                ),
            )

    def test_private_origin_is_configurable_and_native_rss_stays_direct(
        self,
    ) -> None:
        generated = {
            "name": "Gerado",
            "url": "https://publisher.example/",
            "scraper": "FakeScraper",
            "feed_file": "generated.xml",
            "group": "outros",
        }
        native = {
            "name": "Nativo",
            "url": "https://native.example/feed.xml",
            "scraper": "ExistingRssScraper",
            "feed_file": "native.xml",
            "group": "clima",
        }
        with patch.dict(
            os.environ,
            {"FEED_BASE_URL": "https://feeds.paulofehlauer.com"},
            clear=True,
        ):
            self.assertEqual(
                get_source_feed_url(generated),
                "https://feeds.paulofehlauer.com/feeds/generated.xml",
            )
            self.assertEqual(
                get_source_feed_url(native),
                "https://native.example/feed.xml",
            )
            self.assertEqual(
                get_opml_url(),
                "https://feeds.paulofehlauer.com/feeds.opml",
            )
            opml = generate_opml([generated, native])

        urls = [
            outline.get("xmlUrl")
            for outline in opml.findall(".//outline")
            if outline.get("type") == "rss"
        ]
        self.assertEqual(
            sorted(urls),
            sorted(
                [
                    "https://feeds.paulofehlauer.com/feeds/generated.xml",
                    "https://native.example/feed.xml",
                ]
            ),
        )

    def test_credentials_are_forbidden_in_feed_base_url(self) -> None:
        for invalid in (
            "",
            "https://user:password@example.com",
            "https://example.com/private/path",
            "https://example.com:8443",
        ):
            with (
                self.subTest(invalid=invalid),
                patch.dict(
                    os.environ,
                    {"FEED_BASE_URL": invalid},
                    clear=True,
                ),
                self.assertRaises(ValueError),
            ):
                get_feed_base_url()

    def test_main_rejects_invalid_origin_before_loading_sources(self) -> None:
        import main as scraper_main

        with (
            patch.dict(
                os.environ,
                {"FEED_BASE_URL": "http://insecure.example"},
                clear=True,
            ),
            patch.object(scraper_main, "ensure_directories"),
            patch.object(scraper_main, "load_sources_config") as load_sources,
            self.assertRaises(ValueError),
        ):
            scraper_main.main()
        load_sources.assert_not_called()

    def test_self_link_migration_preserves_items_and_guids(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            feed_path = root / "feeds" / "preserved.xml"
            article_url = "https://publisher.example/article"
            description = "<p>conteúdo integral preservado</p>"
            write_feed(
                feed_path,
                self_url=(
                    "https://paulofeh.github.io/rss-de-valor/"
                    "feeds/preserved.xml"
                ),
                article_url=article_url,
                description=description,
                duplicate_guid=True,
            )
            previous_cwd = Path.cwd()
            try:
                os.chdir(root)
                with patch.dict(
                    os.environ,
                    {"FEED_BASE_URL": "https://pilot.example.workers.dev"},
                    clear=False,
                ):
                    self.assertTrue(
                        normalize_feed_self_link("preserved.xml")
                    )
            finally:
                os.chdir(previous_cwd)

            parsed = ET.parse(feed_path).getroot()
            channel = parsed.find("channel")
            self.assertIsNotNone(channel)
            self_link = channel.find(
                "{http://www.w3.org/2005/Atom}link"
            )
            self.assertEqual(
                self_link.get("href"),
                "https://pilot.example.workers.dev/feeds/preserved.xml",
            )
            item = channel.find("item")
            self.assertEqual(item.findtext("link"), article_url)
            self.assertEqual(
                [guid.text for guid in item.findall("guid")],
                [article_url, article_url],
            )
            self.assertEqual(item.findtext("description"), description)


if __name__ == "__main__":
    unittest.main()
