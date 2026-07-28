from __future__ import annotations

import html
import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Mapping
from xml.etree import ElementTree as ET

from scripts.private_feed_common import (
    CANONICAL_FEED_BASE_URL,
    PreconditionFailed,
    StorageOperationError,
    StoredObject,
    canonical_json_bytes,
    sha256_bytes,
)


class FakeObjectStore:
    def __init__(self) -> None:
        self.objects: dict[str, StoredObject] = {}
        self._version = 0
        self.put_attempts = 0
        self.fail_on_put_number: int | None = None
        self.current_gets = 0
        self.on_current_get: Callable[["FakeObjectStore", int], None] | None = None

    def _next_etag(self) -> str:
        self._version += 1
        return f'"fake-etag-{self._version}"'

    def put(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str,
        metadata: Mapping[str, str],
        if_match: str | None = None,
        if_none_match: bool = False,
    ) -> StoredObject:
        self.put_attempts += 1
        if self.fail_on_put_number == self.put_attempts:
            raise StorageOperationError("injected upload interruption")
        existing = self.objects.get(key)
        if if_none_match and existing is not None:
            raise PreconditionFailed("injected If-None-Match failure")
        if if_match is not None and (
            existing is None or existing.etag != if_match
        ):
            raise PreconditionFailed("injected If-Match failure")
        stored = StoredObject(
            key=key,
            etag=self._next_etag(),
            size=len(data),
            last_modified=datetime.now(timezone.utc),
            content_type=content_type,
            metadata=dict(metadata),
            data=bytes(data),
        )
        self.objects[key] = stored
        return replace(stored, data=None)

    def direct_put(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str = "application/json; charset=utf-8",
        metadata: Mapping[str, str] | None = None,
    ) -> StoredObject:
        stored = StoredObject(
            key=key,
            etag=self._next_etag(),
            size=len(data),
            last_modified=datetime.now(timezone.utc),
            content_type=content_type,
            metadata=dict(metadata or {"sha256": sha256_bytes(data)}),
            data=bytes(data),
        )
        self.objects[key] = stored
        return stored

    def get(self, key: str) -> StoredObject | None:
        if key == "current.json":
            self.current_gets += 1
            if self.on_current_get is not None:
                self.on_current_get(self, self.current_gets)
        return self.objects.get(key)

    def head(self, key: str) -> StoredObject | None:
        stored = self.objects.get(key)
        return replace(stored, data=None) if stored is not None else None

    def list_keys(self, prefix: str) -> list[str]:
        return sorted(key for key in self.objects if key.startswith(prefix))

    def delete_keys(self, keys: Iterable[str]) -> None:
        for key in keys:
            self.objects.pop(key, None)


def write_feed(
    path: Path,
    *,
    self_url: str,
    article_url: str,
    description: str,
    author: str = "Autora Teste",
    duplicate_guid: bool = False,
    pubdate: str = "Thu, 24 Jul 2026 12:00:00 +0000",
) -> None:
    guid = (
        f"<guid isPermaLink=\"true\">{html.escape(article_url)}</guid>"
    )
    if duplicate_guid:
        guid += guid
    value = f"""<?xml version="1.0" encoding="utf-8"?>
<rss xmlns:atom="http://www.w3.org/2005/Atom"
     xmlns:dc="http://purl.org/dc/elements/1.1/"
     version="2.0">
  <channel>
    <title>Feed de teste</title>
    <link>https://publisher.example/</link>
    <description>Teste</description>
    <atom:link href="{html.escape(self_url)}" rel="self"
               type="application/rss+xml" />
    <item>
      <title>Artigo de teste</title>
      <link>{html.escape(article_url)}</link>
      <description>{html.escape(description)}</description>
      <dc:creator>{html.escape(author)}</dc:creator>
      <pubDate>{pubdate}</pubDate>
      {guid}
    </item>
  </channel>
</rss>
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def write_opml(path: Path, sources: list[dict[str, str]]) -> None:
    root = ET.Element("opml", version="2.0")
    ET.SubElement(root, "head")
    body = ET.SubElement(root, "body")
    for source in sources:
        if source["scraper"] == "ExistingRssScraper":
            url = source["url"]
        else:
            url = (
                f"{CANONICAL_FEED_BASE_URL}/feeds/{source['feed_file']}"
            )
        ET.SubElement(
            body,
            "outline",
            type="rss",
            text=source["name"],
            title=source["name"],
            xmlUrl=url,
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def write_folha_migration_pair(
    root: Path,
    source: Mapping[str, str],
) -> None:
    feed_file = source["feed_file"]
    links = [
        (
            "https://www1.folha.uol.com.br/colunas/"
            f"{source['slug']}/2026/07/artigo-{index}.shtml"
        )
        for index in range(10)
    ]
    items = "\n".join(
        f"""    <item>
      <title>Artigo {index}</title>
      <link>{html.escape(link)}</link>
      <description>{html.escape('conteudo completo ' * 80)}</description>
      <dc:creator>{html.escape(source['name'])}</dc:creator>
      <pubDate>Thu, 24 Jul 2026 12:00:00 +0000</pubDate>
      <guid isPermaLink="true">{html.escape(link)}</guid>
    </item>"""
        for index, link in enumerate(links)
    )
    feed = f"""<?xml version="1.0" encoding="utf-8"?>
<rss xmlns:atom="http://www.w3.org/2005/Atom"
     xmlns:dc="http://purl.org/dc/elements/1.1/"
     version="2.0">
  <channel>
    <title>{html.escape(source['name'])}</title>
    <link>https://www1.folha.uol.com.br/</link>
    <description>Fixture da migração Folha</description>
    <atom:link href="{CANONICAL_FEED_BASE_URL}/feeds/{feed_file}"
               rel="self" type="application/rss+xml" />
{items}
  </channel>
</rss>
"""
    feed_path = root / "feeds" / feed_file
    feed_path.parent.mkdir(parents=True, exist_ok=True)
    feed_path.write_text(feed, encoding="utf-8")
    history_path = root / "history" / source["history_file"]
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text(
        json.dumps({"last_article_link": links[0]}),
        encoding="utf-8",
    )


def create_test_repository(root: Path) -> list[dict[str, str]]:
    (root / "config").mkdir(parents=True)
    (root / "feeds").mkdir()
    (root / "history").mkdir()

    sources = [
        {
            "name": "Fonte comum",
            "url": "https://publisher.example/plain",
            "scraper": "FakeScraper",
            "feed_file": "plain_feed.xml",
            "history_file": "plain_history.json",
            "group": "outros",
        },
        {
            "name": "LinkedIn teste",
            "url": "https://linkedin.example/newsletter",
            "scraper": "LinkedInNewsletterScraper",
            "feed_file": "linkedin_feed.xml",
            "history_file": "linkedin_history.json",
            "group": "linkedin",
        },
        {
            "name": "Folha teste",
            "url": "https://folha.example/coluna",
            "scraper": "FolhaRssFullContentScraper",
            "feed_file": "folha_feed.xml",
            "history_file": "folha_history.json",
            "group": "folha",
        },
        {
            "name": "RSS nativo",
            "url": "https://native.example/feed.xml",
            "scraper": "ExistingRssScraper",
            "feed_file": "native_feed.xml",
            "history_file": "native_history.json",
            "group": "clima",
        },
    ]
    (root / "config" / "sources_config.json").write_text(
        json.dumps({"sources": sources}, ensure_ascii=False),
        encoding="utf-8",
    )
    policy = {
        "schema_version": 1,
        "source_policy": {
            "include_configured_sources": True,
            "excluded_scrapers": ["ExistingRssScraper"],
        },
        "metadata": [
            {
                "local_path": "feeds/feeds.opml",
                "object_path": "metadata/feeds.opml",
                "public_path": "/feeds.opml",
                "content_type": "text/x-opml; charset=utf-8",
                "publish_in_full": True,
                "publish_in_pilot": False,
            }
        ],
        "aggregate_feed_files": [],
        "publish_index_html": False,
        "limits": {
            "max_object_bytes": 1024 * 1024,
            "max_manifest_objects": 100,
        },
    }
    (root / "config" / "private_publication_allowlist.json").write_text(
        json.dumps(policy),
        encoding="utf-8",
    )

    for index, source in enumerate(sources):
        if source["scraper"] == "ExistingRssScraper":
            continue
        write_feed(
            root / "feeds" / source["feed_file"],
            self_url=(
                f"{CANONICAL_FEED_BASE_URL}/feeds/{source['feed_file']}"
            ),
            article_url=f"https://publisher.example/article-{index}",
            description=f"<p>{'conteudo ' * 90}</p>",
            duplicate_guid=index == 0,
        )
        (root / "history" / source["history_file"]).write_text(
            json.dumps(
                {
                    "last_article_link":
                        f"https://publisher.example/article-{index}"
                }
            ),
            encoding="utf-8",
        )
    write_opml(root / "feeds" / "feeds.opml", sources)
    return sources


def current_run_id(store: FakeObjectStore) -> str | None:
    stored = store.objects.get("current.json")
    if stored is None or stored.data is None:
        return None
    return json.loads(stored.data.decode("utf-8"))["run_id"]


def competitor_pointer(run_id: str = "competing-run") -> bytes:
    manifest = canonical_json_bytes({"competing": True})
    return canonical_json_bytes(
        {
            "schema_version": 1,
            "run_id": run_id,
            "manifest_key": f"snapshots/{run_id}/manifest.json",
            "manifest_sha256": sha256_bytes(manifest),
            "published_at": "2026-07-24T12:00:00Z",
        }
    )
