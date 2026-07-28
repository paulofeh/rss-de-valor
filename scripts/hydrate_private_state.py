"""Hydrate feeds and histories from the active private R2 snapshot."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

try:
    from .private_feed_common import (
        DEFAULT_STATE_DIR,
        BootstrapRequired,
        ManifestError,
        ObjectStore,
        PublicationError,
        S3ObjectStore,
        build_object_specs,
        load_active_remote_state,
        load_publication_policy,
        load_source_inventory,
        local_path_for_object,
        sha256_bytes,
        write_json_file,
    )
except ImportError:  # pragma: no cover - direct script execution
    from private_feed_common import (  # type: ignore[no-redef]
        DEFAULT_STATE_DIR,
        BootstrapRequired,
        ManifestError,
        ObjectStore,
        PublicationError,
        S3ObjectStore,
        build_object_specs,
        load_active_remote_state,
        load_publication_policy,
        load_source_inventory,
        local_path_for_object,
        sha256_bytes,
        write_json_file,
    )


def _replace_directory(source: Path, destination: Path) -> None:
    old = destination.with_name(f".{destination.name}.old")
    if old.exists():
        shutil.rmtree(old)
    if destination.exists():
        os.replace(destination, old)
    os.replace(source, destination)
    shutil.rmtree(old, ignore_errors=True)


def _write_bootstrap_baseline(
    *,
    repo_root: Path,
    state_dir: Path,
    object_paths: list[str],
) -> None:
    temporary_root = Path(tempfile.mkdtemp(prefix=".bootstrap-", dir=state_dir))
    try:
        baseline = temporary_root / "baseline"
        for object_path in object_paths:
            source = local_path_for_object(repo_root, object_path)
            if not source.is_file():
                raise BootstrapRequired(
                    f"bootstrap artifact is absent: {source}"
                )
            destination = baseline / object_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
        _replace_directory(baseline, state_dir / "baseline")
    finally:
        shutil.rmtree(temporary_root, ignore_errors=True)


def hydrate_private_state(
    *,
    store: ObjectStore,
    repo_root: Path,
    state_dir: Path,
    allow_bootstrap_from_local: bool,
    missing_object_profile: str | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    state_dir = state_dir.resolve()
    state_dir.mkdir(parents=True, exist_ok=True)
    policy = load_publication_policy(repo_root)
    inventory = load_source_inventory(repo_root)
    specs = build_object_specs(repo_root, inventory, policy)
    expected_object_paths = sorted(spec.object_path for spec in specs)

    active = load_active_remote_state(store, policy=policy)
    if active is None:
        if not allow_bootstrap_from_local:
            raise BootstrapRequired(
                "current.json is absent; rerun with explicit bootstrap authorization"
            )
        _write_bootstrap_baseline(
            repo_root=repo_root,
            state_dir=state_dir,
            object_paths=expected_object_paths,
        )
        hydration = {
            "schema_version": 1,
            "bootstrap": True,
            "observed_current_etag": None,
            "observed_current_sha256": None,
            "run_id": None,
        }
        write_json_file(state_dir / "hydration.json", hydration)
        return {
            "status": "bootstrap",
            "objects": len(expected_object_paths),
            "run_id": None,
        }

    current_object, pointer, manifest_object, manifest = active
    expected_object_path_set = set(expected_object_paths)
    manifest_object_paths = set(manifest["objects"])
    missing_object_paths = expected_object_path_set - manifest_object_paths
    seed_object_data: dict[str, bytes] = {}
    if missing_object_profile:
        try:
            from .migrate_folha_sources import approved_seed_objects
        except ImportError:  # pragma: no cover - direct script execution
            from migrate_folha_sources import approved_seed_objects

        seed_object_data = approved_seed_objects(
            repo_root=repo_root,
            profile=missing_object_profile,
        )
        if missing_object_paths != set(seed_object_data):
            raise ManifestError(
                "Folha source migration did not observe its exact missing "
                "object set"
            )
    elif missing_object_paths:
        raise ManifestError(
            "active snapshot is missing objects required by source configuration"
        )
    ignored_legacy_objects = len(
        manifest_object_paths - expected_object_path_set
    )
    if current_object.data is None or manifest_object.data is None:
        raise ManifestError("active state bodies were not returned")

    temporary_root = Path(tempfile.mkdtemp(prefix=".hydrate-", dir=state_dir))
    staged = temporary_root / "staged"
    baseline = temporary_root / "baseline"
    try:
        for object_path in expected_object_paths:
            if object_path in seed_object_data:
                data = seed_object_data[object_path]
            else:
                entry = manifest["objects"][object_path]
                stored = store.get(entry["key"])
                if stored is None or stored.data is None:
                    raise ManifestError(
                        "active snapshot contains an absent object"
                    )
                if (
                    stored.size != entry["size"]
                    or len(stored.data) != entry["size"]
                    or sha256_bytes(stored.data) != entry["sha256"]
                    or stored.metadata.get("sha256") != entry["sha256"]
                ):
                    raise ManifestError(
                        "active snapshot object hash or size diverged"
                    )
                data = stored.data
            staged_path = staged / object_path
            staged_path.parent.mkdir(parents=True, exist_ok=True)
            staged_path.write_bytes(data)
            baseline_path = baseline / object_path
            baseline_path.parent.mkdir(parents=True, exist_ok=True)
            baseline_path.write_bytes(data)

        # No working-tree file is replaced until every remote object has passed
        # size, metadata and SHA-256 validation.
        for object_path in expected_object_paths:
            destination = local_path_for_object(repo_root, object_path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staged / object_path, destination)
        _replace_directory(baseline, state_dir / "baseline")

        (state_dir / "active-current.json").write_bytes(current_object.data)
        (state_dir / "active-manifest.json").write_bytes(manifest_object.data)
        hydration = {
            "schema_version": 1,
            "bootstrap": False,
            "observed_current_etag": current_object.etag,
            "observed_current_sha256": sha256_bytes(current_object.data),
            "run_id": pointer["run_id"],
            "ignored_legacy_objects": ignored_legacy_objects,
            "missing_object_profile": missing_object_profile,
            "seeded_objects": len(seed_object_data),
        }
        write_json_file(state_dir / "hydration.json", hydration)
    finally:
        shutil.rmtree(temporary_root, ignore_errors=True)

    return {
        "status": "hydrated",
        "objects": len(expected_object_paths),
        "ignored_legacy_objects": ignored_legacy_objects,
        "missing_object_profile": missing_object_profile,
        "seeded_objects": len(seed_object_data),
        "run_id": pointer["run_id"],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIR)
    parser.add_argument(
        "--allow-bootstrap-from-local",
        action="store_true",
        help="Use the current public tree only when R2 has no current.json.",
    )
    parser.add_argument(
        "--missing-object-profile",
        help=(
            "Allow one fixed, validated set of newly configured local "
            "objects during hydration."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    repo_root = arguments.repo_root.resolve()
    state_dir = (
        arguments.state_dir
        if arguments.state_dir.is_absolute()
        else repo_root / arguments.state_dir
    )
    try:
        result = hydrate_private_state(
            store=S3ObjectStore.from_environment(),
            repo_root=repo_root,
            state_dir=state_dir,
            allow_bootstrap_from_local=arguments.allow_bootstrap_from_local,
            missing_object_profile=arguments.missing_object_profile,
        )
    except PublicationError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
