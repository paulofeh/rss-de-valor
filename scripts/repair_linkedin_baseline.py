"""Stage and restore an explicitly allowlisted LinkedIn repair baseline.

The private publisher normally replaces every local feed and history with the
active R2 snapshot before running scrapers. This helper permits a confirmed
manual workflow to carry known-complete, checked-in LinkedIn artifacts across
that hydration boundary. It never reads or writes R2 and does not publish.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET

try:
    from .private_feed_common import (
        ConfigurationError,
        PublicationError,
        canonical_json_bytes,
        load_source_inventory,
        sha256_bytes,
        write_json_file,
    )
except ImportError:  # pragma: no cover - direct script execution
    from private_feed_common import (  # type: ignore[no-redef]
        ConfigurationError,
        PublicationError,
        canonical_json_bytes,
        load_source_inventory,
        sha256_bytes,
        write_json_file,
    )


PROFILE_NAME = "linkedin-full-content-2026-07-27"
REPAIR_SOURCE_NAMES = frozenset(
    {
        "Becoming Net Positive",
        "Do Impacto ao Mercado",
        "IA Sem Hype",
        "Instituto Cidades Responsivas",
        "Magnífica Newsletter do Gabs",
        "Natureza, clima e negócios",
        "OSPA Place",
        "Perspectivas ESG by VMF",
        "Planta baixa, juros altos",
        "Risco & Estratégia na Mineração",
        "Storyskills",
        "Talking Climate",
    }
)
EXPECTED_SOURCE_COUNT = 12
EXPECTED_OBJECT_COUNT = EXPECTED_SOURCE_COUNT * 2
MIN_DESCRIPTION_CHARACTERS = 200
EXPECTED_ITEMS_PER_FEED = 5
DC_CREATOR_TAG = "{http://purl.org/dc/elements/1.1/}creator"
ATOM_LINK_TAG = "{http://www.w3.org/2005/Atom}link"


class BaselineRepairError(PublicationError):
    """The local LinkedIn repair baseline is absent, invalid, or divergent."""


def _repair_sources(repo_root: Path) -> list[dict[str, Any]]:
    inventory = load_source_inventory(repo_root)
    sources = [
        dict(source)
        for source in inventory.source_by_feed_file.values()
        if source.get("name") in REPAIR_SOURCE_NAMES
    ]
    actual_names = {source.get("name") for source in sources}
    if actual_names != REPAIR_SOURCE_NAMES:
        missing = sorted(REPAIR_SOURCE_NAMES - actual_names)
        unexpected = sorted(actual_names - REPAIR_SOURCE_NAMES)
        raise ConfigurationError(
            "LinkedIn repair source inventory diverged: "
            f"missing={missing}, unexpected={unexpected}"
        )
    if len(sources) != EXPECTED_SOURCE_COUNT:
        raise ConfigurationError("LinkedIn repair source inventory is ambiguous")
    for source in sources:
        if source.get("scraper") != "LinkedInNewsletterScraper":
            raise ConfigurationError(
                "LinkedIn repair source must use LinkedInNewsletterScraper"
            )
    return sorted(sources, key=lambda source: source["feed_file"])


def _object_paths(sources: list[dict[str, Any]]) -> tuple[str, ...]:
    paths = sorted(
        path
        for source in sources
        for path in (
            f"feeds/{source['feed_file']}",
            f"history/{source['history_file']}",
        )
    )
    if len(paths) != EXPECTED_OBJECT_COUNT or len(paths) != len(set(paths)):
        raise ConfigurationError("LinkedIn repair object inventory is invalid")
    return tuple(paths)


def _validate_feed_and_history(
    *,
    feed_data: bytes,
    history_data: bytes,
    feed_file: str,
) -> None:
    try:
        root = ET.fromstring(feed_data)
    except ET.ParseError as exc:
        raise BaselineRepairError(
            f"LinkedIn repair feed is not valid XML: {feed_file}"
        ) from exc
    channel = root.find("channel")
    if channel is None:
        raise BaselineRepairError(
            f"LinkedIn repair feed has no channel: {feed_file}"
        )
    items = channel.findall("item")
    if len(items) != EXPECTED_ITEMS_PER_FEED:
        raise BaselineRepairError(
            f"LinkedIn repair feed must contain five items: {feed_file}"
        )

    self_links = [
        element
        for element in channel.findall(ATOM_LINK_TAG)
        if element.get("rel") == "self"
    ]
    if len(self_links) != 1:
        raise BaselineRepairError(
            f"LinkedIn repair feed must contain one self-link: {feed_file}"
        )
    parsed_self_link = urlsplit(self_links[0].get("href", ""))
    if (
        parsed_self_link.scheme != "https"
        or not parsed_self_link.hostname
        or parsed_self_link.username
        or parsed_self_link.password
        or not parsed_self_link.path.endswith(f"/feeds/{feed_file}")
        or parsed_self_link.query
        or parsed_self_link.fragment
    ):
        raise BaselineRepairError(
            f"LinkedIn repair feed self-link is invalid: {feed_file}"
        )

    links: list[str] = []
    for item in items:
        link = (item.findtext("link") or "").strip()
        parsed_link = urlsplit(link)
        author = (item.findtext(DC_CREATOR_TAG) or "").strip()
        description = item.findtext("description") or ""
        if (
            parsed_link.scheme != "https"
            or not parsed_link.hostname
            or (
                parsed_link.hostname != "linkedin.com"
                and not parsed_link.hostname.endswith(".linkedin.com")
            )
            or not parsed_link.path.startswith("/pulse/")
            or parsed_link.username
            or parsed_link.password
            or parsed_link.query
            or parsed_link.fragment
        ):
            raise BaselineRepairError(
                f"LinkedIn repair item URL is invalid: {feed_file}"
            )
        if not author or author == "Autor não encontrado":
            raise BaselineRepairError(
                f"LinkedIn repair item author is absent: {feed_file}"
            )
        if len(description) < MIN_DESCRIPTION_CHARACTERS:
            raise BaselineRepairError(
                f"LinkedIn repair item content is incomplete: {feed_file}"
            )
        links.append(link)
    if len(links) != len(set(links)):
        raise BaselineRepairError(
            f"LinkedIn repair feed contains duplicate items: {feed_file}"
        )

    try:
        history = json.loads(history_data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BaselineRepairError(
            f"LinkedIn repair history is not valid JSON: {feed_file}"
        ) from exc
    if (
        not isinstance(history, dict)
        or set(history) != {"last_article_link"}
        or history["last_article_link"] != links[0]
    ):
        raise BaselineRepairError(
            f"LinkedIn repair history does not match the latest item: {feed_file}"
        )


def _validate_source_pairs(
    *,
    sources: list[dict[str, Any]],
    object_data: dict[str, bytes],
) -> None:
    for source in sources:
        feed_path = f"feeds/{source['feed_file']}"
        history_path = f"history/{source['history_file']}"
        _validate_feed_and_history(
            feed_data=object_data[feed_path],
            history_data=object_data[history_path],
            feed_file=source["feed_file"],
        )


def stage_repair_baseline(*, repo_root: Path, stage_dir: Path) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    stage_dir = stage_dir.resolve()
    if stage_dir == repo_root or repo_root in stage_dir.parents:
        raise BaselineRepairError(
            "LinkedIn repair stage directory must be outside the repository"
        )
    if stage_dir.exists():
        raise BaselineRepairError("LinkedIn repair stage directory already exists")

    sources = _repair_sources(repo_root)
    object_paths = _object_paths(sources)
    object_data: dict[str, bytes] = {}
    for object_path in object_paths:
        source_path = repo_root / object_path
        if not source_path.is_file() or source_path.is_symlink():
            raise BaselineRepairError(
                f"LinkedIn repair artifact is absent or unsafe: {object_path}"
            )
        object_data[object_path] = source_path.read_bytes()
    _validate_source_pairs(sources=sources, object_data=object_data)

    try:
        for object_path, data in object_data.items():
            destination = stage_dir / "objects" / object_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
        manifest = {
            "schema_version": 1,
            "profile": PROFILE_NAME,
            "sources": sorted(REPAIR_SOURCE_NAMES),
            "objects": {
                object_path: {
                    "sha256": sha256_bytes(data),
                    "size": len(data),
                }
                for object_path, data in sorted(object_data.items())
            },
        }
        write_json_file(stage_dir / "manifest.json", manifest)
    except Exception:
        if stage_dir.exists():
            for path in sorted(
                stage_dir.rglob("*"),
                key=lambda item: len(item.parts),
                reverse=True,
            ):
                if path.is_file():
                    path.unlink()
                elif path.is_dir():
                    path.rmdir()
            stage_dir.rmdir()
        raise

    return {
        "status": "staged",
        "profile": PROFILE_NAME,
        "sources": len(sources),
        "objects": len(object_paths),
    }


def _load_staged_objects(
    *,
    sources: list[dict[str, Any]],
    stage_dir: Path,
) -> dict[str, bytes]:
    manifest_path = stage_dir / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BaselineRepairError(
            "LinkedIn repair stage manifest is absent or invalid"
        ) from exc

    object_paths = _object_paths(sources)
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != 1
        or manifest.get("profile") != PROFILE_NAME
        or manifest.get("sources") != sorted(REPAIR_SOURCE_NAMES)
        or not isinstance(manifest.get("objects"), dict)
        or set(manifest["objects"]) != set(object_paths)
    ):
        raise BaselineRepairError("LinkedIn repair stage manifest diverged")

    object_data: dict[str, bytes] = {}
    for object_path in object_paths:
        entry = manifest["objects"][object_path]
        staged_path = stage_dir / "objects" / object_path
        if (
            not isinstance(entry, dict)
            or not staged_path.is_file()
            or staged_path.is_symlink()
        ):
            raise BaselineRepairError(
                f"LinkedIn repair staged artifact is absent: {object_path}"
            )
        data = staged_path.read_bytes()
        if (
            entry.get("size") != len(data)
            or entry.get("sha256") != sha256_bytes(data)
        ):
            raise BaselineRepairError(
                f"LinkedIn repair staged artifact diverged: {object_path}"
            )
        object_data[object_path] = data
    _validate_source_pairs(sources=sources, object_data=object_data)
    return object_data


def _replace_objects(repo_root: Path, object_data: dict[str, bytes]) -> None:
    originals: dict[Path, bytes] = {}
    temporary_paths: dict[Path, Path] = {}
    replaced: list[Path] = []
    try:
        for object_path, data in object_data.items():
            destination = repo_root / object_path
            if not destination.is_file() or destination.is_symlink():
                raise BaselineRepairError(
                    f"hydrated destination is absent or unsafe: {object_path}"
                )
            originals[destination] = destination.read_bytes()
            temporary = destination.with_name(f".{destination.name}.repair")
            temporary.write_bytes(data)
            temporary_paths[destination] = temporary

        for destination, temporary in temporary_paths.items():
            os.replace(temporary, destination)
            replaced.append(destination)
    except Exception:
        for destination in replaced:
            rollback = destination.with_name(f".{destination.name}.rollback")
            rollback.write_bytes(originals[destination])
            os.replace(rollback, destination)
        raise
    finally:
        for temporary in temporary_paths.values():
            temporary.unlink(missing_ok=True)


def restore_repair_baseline(
    *,
    repo_root: Path,
    stage_dir: Path,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    stage_dir = stage_dir.resolve()
    if stage_dir == repo_root or repo_root in stage_dir.parents:
        raise BaselineRepairError(
            "LinkedIn repair stage directory must be outside the repository"
        )
    sources = _repair_sources(repo_root)
    object_data = _load_staged_objects(
        sources=sources,
        stage_dir=stage_dir,
    )
    _replace_objects(repo_root, object_data)
    return {
        "status": "restored",
        "profile": PROFILE_NAME,
        "sources": len(sources),
        "objects": len(object_data),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("stage", "restore"))
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--stage-dir", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.action == "stage":
            result = stage_repair_baseline(
                repo_root=arguments.repo_root,
                stage_dir=arguments.stage_dir,
            )
        else:
            result = restore_repair_baseline(
                repo_root=arguments.repo_root,
                stage_dir=arguments.stage_dir,
            )
    except PublicationError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(canonical_json_bytes(result).decode("utf-8"), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
