"""Validate generated private-feed state and an optional staged snapshot."""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from xml.etree import ElementTree as ET

try:
    from .private_feed_common import (
        CANONICAL_FEED_BASE_URL,
        DEFAULT_STATE_DIR,
        ConfigurationError,
        ManifestError,
        ObjectSpec,
        PublicationError,
        SourceInventory,
        build_object_specs,
        load_json_file,
        load_publication_policy,
        load_source_inventory,
        read_manifest_bytes,
        secret_values_from_environment,
        sha256_bytes,
    )
except ImportError:  # pragma: no cover - direct script execution
    from private_feed_common import (  # type: ignore[no-redef]
        CANONICAL_FEED_BASE_URL,
        DEFAULT_STATE_DIR,
        ConfigurationError,
        ManifestError,
        ObjectSpec,
        PublicationError,
        SourceInventory,
        build_object_specs,
        load_json_file,
        load_publication_policy,
        load_source_inventory,
        read_manifest_bytes,
        secret_values_from_environment,
        sha256_bytes,
    )


ATOM_NAMESPACE = "http://www.w3.org/2005/Atom"
DC_CREATOR = "{http://purl.org/dc/elements/1.1/}creator"
ENRICHED_SCRAPERS = {
    "LinkedInNewsletterScraper",
    "FolhaRssFullContentScraper",
}
FALLBACK_AUTHORS = {"", "Autor não encontrado"}
TRACKING_QUERY_PARAMETERS = {
    "dclid",
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "msclkid",
    "trk",
}
FORBIDDEN_PRIVATE_HOSTS = {
    "paulofeh.github.io",
    "fehla.xyz",
}
URL_WITH_CREDENTIALS_RE = re.compile(
    rb"https?://[^/\s:@]+:[^@\s/]+@",
    re.IGNORECASE,
)
AUTHORIZATION_VALUE_RE = re.compile(
    rb"authorization\s*:\s*basic\s+[A-Za-z0-9+/=]+",
    re.IGNORECASE,
)


class SnapshotValidationError(PublicationError):
    """One or more publication invariants failed."""


@dataclass(frozen=True)
class FeedItem:
    link: str
    guid: str
    description: str
    author: str
    pubdate: datetime | None


@dataclass(frozen=True)
class ValidationReport:
    generated_feeds: int
    history_files: int
    metadata_files: int
    ignored_xml_files: tuple[str, ...]


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def visible_text(value: str) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(html.unescape(value))
    except Exception:
        return html.unescape(value)
    return " ".join(" ".join(parser.parts).split())


def _error(errors: list[str], message: str) -> None:
    errors.append(message)


def _read_bytes(path: Path, *, max_bytes: int, errors: list[str]) -> bytes | None:
    if path.is_symlink():
        _error(errors, f"artifact must not be a symbolic link: {path}")
        return None
    try:
        stat_result = path.stat()
    except OSError:
        _error(errors, f"required artifact is absent: {path}")
        return None
    if not path.is_file():
        _error(errors, f"artifact is not a regular file: {path}")
        return None
    size = stat_result.st_size
    if size > max_bytes:
        _error(errors, f"artifact exceeds the configured size limit: {path}")
        return None
    try:
        return path.read_bytes()
    except OSError:
        _error(errors, f"artifact could not be read: {path}")
        return None


def _scan_for_secrets(
    path: Path,
    data: bytes,
    secret_values: Iterable[bytes],
    errors: list[str],
) -> None:
    if URL_WITH_CREDENTIALS_RE.search(data):
        _error(errors, f"artifact contains credentials in a URL: {path}")
    if AUTHORIZATION_VALUE_RE.search(data):
        _error(errors, f"artifact contains an Authorization value: {path}")
    for secret in secret_values:
        if len(secret) >= 4 and secret in data:
            _error(errors, f"artifact contains a configured secret value: {path}")
            break


def _parse_pubdate(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None


def _parse_feed(
    path: Path,
    *,
    expected_self_url: str,
    max_bytes: int,
    secret_values: Iterable[bytes],
    errors: list[str],
) -> dict[str, FeedItem]:
    data = _read_bytes(path, max_bytes=max_bytes, errors=errors)
    if data is None:
        return {}
    _scan_for_secrets(path, data, secret_values, errors)
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        _error(errors, f"RSS XML is not well formed: {path}")
        return {}
    if root.tag != "rss":
        _error(errors, f"RSS root element is invalid: {path}")
        return {}
    channel = root.find("channel")
    if channel is None:
        _error(errors, f"RSS channel is absent: {path}")
        return {}

    self_links = [
        element.get("href")
        for element in channel.findall(f"{{{ATOM_NAMESPACE}}}link")
        if element.get("rel") == "self"
    ]
    if self_links != [expected_self_url]:
        _error(errors, f"RSS self-link is not canonical: {path}")

    items = channel.findall("item")
    if not items:
        _error(errors, f"RSS contains no items: {path}")
        return {}

    parsed_items: dict[str, FeedItem] = {}
    for index, item in enumerate(items):
        link = (item.findtext("link") or "").strip()
        descriptions = item.findall("description")
        description = descriptions[0].text or "" if descriptions else ""
        author = (item.findtext(DC_CREATOR) or "").strip()
        guids = item.findall("guid")
        guid_values = [(guid.text or "").strip() for guid in guids]
        if not link:
            _error(errors, f"RSS item {index} has no link: {path}")
            continue
        if not description.strip():
            _error(errors, f"RSS item {index} has no description: {path}")
        if not guid_values or any(not guid for guid in guid_values):
            _error(errors, f"RSS item {index} has an invalid GUID: {path}")
            continue
        if len(set(guid_values)) != 1 or guid_values[0] != link:
            _error(errors, f"RSS item {index} changed its GUID semantics: {path}")
            continue
        if link in parsed_items:
            _error(errors, f"RSS contains a duplicate item link: {path}")
            continue
        parsed_items[link] = FeedItem(
            link=link,
            guid=guid_values[0],
            description=description,
            author=author,
            pubdate=_parse_pubdate(item.findtext("pubDate")),
        )
    return parsed_items


def _validate_history(
    path: Path,
    *,
    max_bytes: int,
    secret_values: Iterable[bytes],
    errors: list[str],
) -> None:
    data = _read_bytes(path, max_bytes=max_bytes, errors=errors)
    if data is None:
        return
    _scan_for_secrets(path, data, secret_values, errors)
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        _error(errors, f"history JSON is invalid: {path}")
        return
    if not isinstance(value, dict):
        _error(errors, f"history JSON must be an object: {path}")
        return
    link = value.get("last_article_link")
    if link is not None and not isinstance(link, str):
        _error(errors, f"history last_article_link is invalid: {path}")


def _validate_no_private_origin_drift(
    url: str,
    *,
    path: Path,
    errors: list[str],
    allow_workers_dev: bool = False,
) -> None:
    try:
        parsed = urlsplit(url)
    except ValueError:
        _error(errors, f"artifact contains an invalid URL: {path}")
        return
    host = (parsed.hostname or "").lower()
    if (
        host in FORBIDDEN_PRIVATE_HOSTS
        or (host.endswith(".workers.dev") and not allow_workers_dev)
        or host.endswith(".fehla.xyz")
    ):
        _error(errors, f"artifact contains a forbidden private-feed origin: {path}")


def _validate_feed_base_url(
    feed_base_url: str,
    *,
    mode: str,
    production: bool,
) -> str:
    candidate = feed_base_url.rstrip("/")
    try:
        parsed = urlsplit(candidate)
        port = parsed.port
    except ValueError as exc:
        raise SnapshotValidationError("FEED_BASE_URL is invalid") from exc
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or port is not None
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise SnapshotValidationError(
            "FEED_BASE_URL must be a credential-free HTTPS origin"
        )
    host = parsed.hostname.lower()
    if host.endswith(".fehla.xyz") or host == "paulofeh.github.io":
        raise SnapshotValidationError("FEED_BASE_URL uses a forbidden origin")
    if production and candidate != CANONICAL_FEED_BASE_URL:
        raise SnapshotValidationError(
            f"production FEED_BASE_URL must be {CANONICAL_FEED_BASE_URL}"
        )
    if (
        mode == "pilot"
        and candidate != CANONICAL_FEED_BASE_URL
        and not host.endswith(".workers.dev")
    ):
        raise SnapshotValidationError(
            "pilot FEED_BASE_URL must use workers.dev or the canonical origin"
        )
    return candidate


def _validate_opml(
    path: Path,
    *,
    inventory: SourceInventory,
    feed_base_url: str,
    max_bytes: int,
    secret_values: Iterable[bytes],
    errors: list[str],
    allow_workers_dev: bool,
) -> None:
    data = _read_bytes(path, max_bytes=max_bytes, errors=errors)
    if data is None:
        return
    _scan_for_secrets(path, data, secret_values, errors)
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        _error(errors, f"OPML XML is not well formed: {path}")
        return
    if root.tag != "opml":
        _error(errors, f"OPML root element is invalid: {path}")
        return

    actual_urls = [
        outline.get("xmlUrl")
        for outline in root.findall(".//outline")
        if outline.get("type") == "rss"
    ]
    if any(url is None for url in actual_urls):
        _error(errors, f"OPML contains an RSS outline without xmlUrl: {path}")
        return
    expected_urls = [
        f"{feed_base_url}/feeds/{feed_file}"
        for feed_file in inventory.generated_feed_files
    ]
    expected_urls.extend(
        str(source["url"]) for source in inventory.native_sources
    )
    if sorted(actual_urls) != sorted(expected_urls):
        _error(errors, f"OPML URLs do not match active source configuration: {path}")
    for url in actual_urls:
        assert url is not None
        _validate_no_private_origin_drift(
            url,
            path=path,
            errors=errors,
            allow_workers_dev=allow_workers_dev,
        )


def _compare_with_baseline(
    *,
    current_items: Mapping[str, FeedItem],
    baseline_path: Path,
    source: Mapping[str, Any],
    current_path: Path,
    max_bytes: int,
    errors: list[str],
) -> None:
    if not baseline_path.exists():
        return
    baseline_errors: list[str] = []
    baseline_items = _parse_feed(
        baseline_path,
        expected_self_url=(
            source.get("_baseline_self_url")
            or f"https://baseline.invalid/feeds/{current_path.name}"
        ),
        max_bytes=max_bytes,
        secret_values=(),
        errors=baseline_errors,
    )
    # A baseline from the public tree has a different self-link by design. Ignore
    # only that expected migration difference; all item-level parse errors remain.
    baseline_errors = [
        error
        for error in baseline_errors
        if "self-link is not canonical" not in error
    ]
    errors.extend(baseline_errors)

    def normalized_link(value: str) -> str:
        try:
            parsed = urlsplit(value)
        except ValueError:
            return value
        identity_query = [
            (name, item)
            for name, item in parse_qsl(
                parsed.query,
                keep_blank_values=True,
            )
            if (
                not name.lower().startswith("utm_")
                and name.lower() not in TRACKING_QUERY_PARAMETERS
            )
        ]
        return urlunsplit(
            (
                parsed.scheme.lower(),
                parsed.netloc.lower(),
                parsed.path.rstrip("/"),
                urlencode(identity_query, doseq=True),
                "",
            )
        )

    def by_normalized_link(
        items: Mapping[str, FeedItem],
        *,
        label: str,
    ) -> dict[str, FeedItem]:
        normalized: dict[str, FeedItem] = {}
        for link, item in items.items():
            key = normalized_link(link)
            if key in normalized:
                _error(
                    errors,
                    f"{label} RSS contains duplicate tracking variants: {current_path}",
                )
                continue
            normalized[key] = item
        return normalized

    current_by_link = by_normalized_link(current_items, label="current")
    baseline_by_link = by_normalized_link(baseline_items, label="baseline")
    enriched = source.get("scraper") in ENRICHED_SCRAPERS
    for link in sorted(set(current_by_link).intersection(baseline_by_link)):
        current = current_by_link[link]
        baseline = baseline_by_link[link]
        if normalized_link(current.guid) != normalized_link(baseline.guid):
            _error(errors, f"known item GUID changed: {current_path}")
        if not enriched:
            continue
        baseline_length = len(visible_text(baseline.description))
        current_length = len(visible_text(current.description))
        if (
            baseline_length >= 500
            and current_length < max(200, baseline_length // 2)
        ):
            _error(errors, f"known enriched item lost substantial content: {current_path}")
        if (
            baseline.author not in FALLBACK_AUTHORS
            and current.author in FALLBACK_AUTHORS
        ):
            _error(errors, f"known enriched item lost its author: {current_path}")
        if (
            baseline.pubdate is not None
            and current.pubdate is not None
            and baseline.pubdate != current.pubdate
        ):
            _error(errors, f"known enriched item changed its publication date: {current_path}")


def expected_routes(
    *,
    specs: Iterable[ObjectSpec],
    mode: str,
    pilot_feed_file: str | None,
) -> dict[str, dict[str, str]]:
    if mode not in {"pilot", "full"}:
        raise ConfigurationError("publication mode must be pilot or full")
    specs_by_public_path = {
        spec.public_path: spec
        for spec in specs
        if spec.public_path is not None
    }
    if mode == "pilot":
        if not pilot_feed_file:
            raise ConfigurationError("pilot mode requires a pilot feed file")
        pilot_path = f"/feeds/{pilot_feed_file}"
        spec = specs_by_public_path.get(pilot_path)
        if spec is None or spec.kind != "feed":
            raise ConfigurationError("pilot feed is not an active generated source")
        routes = {pilot_path: {"object_path": spec.object_path}}
        for public_path, metadata_spec in sorted(specs_by_public_path.items()):
            if metadata_spec.kind == "metadata" and metadata_spec.publish_in_pilot:
                routes[public_path] = {"object_path": metadata_spec.object_path}
        return routes

    routes: dict[str, dict[str, str]] = {}
    for public_path, spec in sorted(specs_by_public_path.items()):
        if spec.publish_in_full:
            routes[public_path] = {"object_path": spec.object_path}
    return routes


def validate_working_state(
    *,
    repo_root: Path,
    feed_base_url: str,
    mode: str,
    pilot_feed_file: str | None,
    baseline_dir: Path | None,
    secret_values: Iterable[bytes] = (),
    production: bool = True,
) -> ValidationReport:
    repo_root = repo_root.resolve()
    feed_base_url = _validate_feed_base_url(
        feed_base_url,
        mode=mode,
        production=production,
    )
    errors: list[str] = []
    _validate_no_private_origin_drift(
        feed_base_url,
        path=repo_root / "config",
        errors=errors,
        allow_workers_dev=mode == "pilot",
    )

    inventory = load_source_inventory(repo_root)
    policy = load_publication_policy(repo_root)
    specs = build_object_specs(repo_root, inventory, policy)
    expected_routes(
        specs=specs,
        mode=mode,
        pilot_feed_file=pilot_feed_file,
    )
    max_bytes = policy["limits"]["max_object_bytes"]

    for feed_file in inventory.generated_feed_files:
        path = repo_root / "feeds" / feed_file
        current_items = _parse_feed(
            path,
            expected_self_url=f"{feed_base_url}/feeds/{feed_file}",
            max_bytes=max_bytes,
            secret_values=secret_values,
            errors=errors,
        )
        source = inventory.source_by_feed_file[feed_file]
        if baseline_dir is not None:
            _compare_with_baseline(
                current_items=current_items,
                baseline_path=baseline_dir / "feeds" / feed_file,
                source=source,
                current_path=path,
                max_bytes=max_bytes,
                errors=errors,
            )

    for history_file in inventory.generated_history_files:
        _validate_history(
            repo_root / "history" / history_file,
            max_bytes=max_bytes,
            secret_values=secret_values,
            errors=errors,
        )

    metadata_count = 0
    for spec in specs:
        if spec.kind != "metadata":
            continue
        metadata_count += 1
        if spec.object_path == "metadata/feeds.opml":
            _validate_opml(
                spec.local_path,
                inventory=inventory,
                feed_base_url=feed_base_url,
                max_bytes=max_bytes,
                secret_values=secret_values,
                errors=errors,
                allow_workers_dev=mode == "pilot",
            )
        else:
            data = _read_bytes(
                spec.local_path,
                max_bytes=max_bytes,
                errors=errors,
            )
            if data is not None:
                _scan_for_secrets(spec.local_path, data, secret_values, errors)

    configured_xml = set(inventory.source_by_feed_file)
    disk_xml = {path.name for path in (repo_root / "feeds").glob("*.xml")}
    ignored_xml = tuple(sorted(disk_xml - configured_xml))

    if errors:
        raise SnapshotValidationError(
            "snapshot validation failed:\n- " + "\n- ".join(sorted(set(errors)))
        )
    return ValidationReport(
        generated_feeds=len(inventory.generated_feed_files),
        history_files=len(inventory.generated_history_files),
        metadata_files=metadata_count,
        ignored_xml_files=ignored_xml,
    )


def validate_snapshot_directory(
    *,
    repo_root: Path,
    snapshot_dir: Path,
    feed_base_url: str,
    mode: str,
    pilot_feed_file: str | None,
    secret_values: Iterable[bytes] = (),
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    snapshot_dir = snapshot_dir.resolve()
    policy = load_publication_policy(repo_root)
    inventory = load_source_inventory(repo_root)
    specs = build_object_specs(repo_root, inventory, policy)
    expected_object_paths = {spec.object_path for spec in specs}
    specs_by_object_path = {spec.object_path: spec for spec in specs}
    expected_route_map = expected_routes(
        specs=specs,
        mode=mode,
        pilot_feed_file=pilot_feed_file,
    )
    feed_base_url = _validate_feed_base_url(
        feed_base_url,
        mode=mode,
        production=mode == "full",
    )

    manifest_path = snapshot_dir / "manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise SnapshotValidationError(
            "staged manifest.json must be a regular non-symlink file"
        )
    try:
        manifest_bytes = manifest_path.read_bytes()
    except OSError as exc:
        raise SnapshotValidationError("staged manifest.json is absent") from exc
    manifest = read_manifest_bytes(
        manifest_bytes,
        max_object_bytes=policy["limits"]["max_object_bytes"],
        max_manifest_objects=policy["limits"]["max_manifest_objects"],
    )
    if set(manifest["objects"]) != expected_object_paths:
        raise SnapshotValidationError(
            "staged manifest object allowlist does not match configuration"
        )
    if manifest["routes"] != expected_route_map:
        raise SnapshotValidationError(
            "staged manifest route allowlist does not match publication mode"
        )
    errors: list[str] = []
    expected_files = {"manifest.json"}
    for object_path, entry in manifest["objects"].items():
        expected_files.add(object_path)
        local = snapshot_dir / object_path
        if entry["content_type"] != specs_by_object_path[object_path].content_type:
            _error(
                errors,
                f"staged object content type differs from allowlist: {local}",
            )
        data = _read_bytes(
            local,
            max_bytes=policy["limits"]["max_object_bytes"],
            errors=errors,
        )
        if data is None:
            continue
        if len(data) != entry["size"] or sha256_bytes(data) != entry["sha256"]:
            _error(errors, f"staged object hash or size differs from manifest: {local}")
        _scan_for_secrets(local, data, secret_values, errors)

    for feed_file in inventory.generated_feed_files:
        _parse_feed(
            snapshot_dir / "feeds" / feed_file,
            expected_self_url=f"{feed_base_url.rstrip('/')}/feeds/{feed_file}",
            max_bytes=policy["limits"]["max_object_bytes"],
            secret_values=secret_values,
            errors=errors,
        )
    for history_file in inventory.generated_history_files:
        _validate_history(
            snapshot_dir / "history" / history_file,
            max_bytes=policy["limits"]["max_object_bytes"],
            secret_values=secret_values,
            errors=errors,
        )
    for spec in specs:
        if spec.object_path == "metadata/feeds.opml":
            _validate_opml(
                snapshot_dir / spec.object_path,
                inventory=inventory,
                feed_base_url=feed_base_url.rstrip("/"),
                max_bytes=policy["limits"]["max_object_bytes"],
                secret_values=secret_values,
                errors=errors,
                allow_workers_dev=mode == "pilot",
            )

    actual_files = {
        path.relative_to(snapshot_dir).as_posix()
        for path in snapshot_dir.rglob("*")
        if path.is_file()
    }
    if actual_files != expected_files:
        _error(errors, "staged snapshot contains missing or non-allowlisted files")
    _scan_for_secrets(manifest_path, manifest_bytes, secret_values, errors)

    if errors:
        raise SnapshotValidationError(
            "staged snapshot validation failed:\n- "
            + "\n- ".join(sorted(set(errors)))
        )
    return manifest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--feed-base-url", required=True)
    parser.add_argument("--mode", choices=("pilot", "full"), required=True)
    parser.add_argument("--pilot-feed-file")
    parser.add_argument("--baseline-dir", type=Path)
    parser.add_argument("--snapshot-dir", type=Path)
    parser.add_argument(
        "--secret-env",
        action="append",
        default=[],
        help="Environment variable whose value must not appear in artifacts.",
    )
    parser.add_argument(
        "--allow-noncanonical-base-url",
        action="store_true",
        help="Local test-only override; never use for production publication.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    repo_root = arguments.repo_root.resolve()
    baseline_dir = arguments.baseline_dir
    if baseline_dir is None:
        candidate = repo_root / DEFAULT_STATE_DIR / "baseline"
        baseline_dir = candidate if candidate.exists() else None
    secrets = secret_values_from_environment(arguments.secret_env)
    try:
        report = validate_working_state(
            repo_root=repo_root,
            feed_base_url=arguments.feed_base_url,
            mode=arguments.mode,
            pilot_feed_file=arguments.pilot_feed_file,
            baseline_dir=baseline_dir,
            secret_values=secrets,
            production=not arguments.allow_noncanonical_base_url,
        )
        if arguments.snapshot_dir:
            validate_snapshot_directory(
                repo_root=repo_root,
                snapshot_dir=arguments.snapshot_dir,
                feed_base_url=arguments.feed_base_url,
                mode=arguments.mode,
                pilot_feed_file=arguments.pilot_feed_file,
                secret_values=secrets,
            )
    except (PublicationError, ConfigurationError, ManifestError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "status": "ok",
                "generated_feeds": report.generated_feeds,
                "history_files": report.history_files,
                "metadata_files": report.metadata_files,
                "ignored_xml_files": list(report.ignored_xml_files),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
