"""Stage an immutable, allowlisted snapshot and build its manifest."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

try:
    from .private_feed_common import (
        DEFAULT_STATE_DIR,
        SAFE_REVISION_RE,
        SAFE_RUN_ID_RE,
        ConfigurationError,
        ManifestError,
        PublicationError,
        build_object_specs,
        canonical_json_bytes,
        isoformat_z,
        load_publication_policy,
        load_source_inventory,
        secret_values_from_environment,
        sha256_bytes,
        utc_now,
        validate_manifest,
    )
    from .validate_snapshot import (
        SnapshotValidationError,
        expected_routes,
        validate_snapshot_directory,
        validate_working_state,
    )
except ImportError:  # pragma: no cover - direct script execution
    from private_feed_common import (  # type: ignore[no-redef]
        DEFAULT_STATE_DIR,
        SAFE_REVISION_RE,
        SAFE_RUN_ID_RE,
        ConfigurationError,
        ManifestError,
        PublicationError,
        build_object_specs,
        canonical_json_bytes,
        isoformat_z,
        load_publication_policy,
        load_source_inventory,
        secret_values_from_environment,
        sha256_bytes,
        utc_now,
        validate_manifest,
    )
    from validate_snapshot import (  # type: ignore[no-redef]
        SnapshotValidationError,
        expected_routes,
        validate_snapshot_directory,
        validate_working_state,
    )


def source_revision(repo_root: Path, explicit: str | None = None) -> str:
    candidate = explicit or os.environ.get("GITHUB_SHA")
    if not candidate:
        result = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=repo_root,
            check=False,
            capture_output=True,
            text=True,
        )
        candidate = result.stdout.strip() if result.returncode == 0 else "unknown"
    candidate = candidate[:128]
    if not SAFE_REVISION_RE.fullmatch(candidate):
        raise ConfigurationError("source revision contains unsafe characters")
    return candidate


def default_run_id(created_at: datetime, revision: str) -> str:
    timestamp = created_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    candidate = f"{timestamp}-{revision[:12]}"
    if not SAFE_RUN_ID_RE.fullmatch(candidate):
        raise ConfigurationError("generated run_id is invalid")
    return candidate


def load_previous_manifest(state_dir: Path) -> Mapping[str, Any] | None:
    path = state_dir / "active-manifest.json"
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ManifestError("local active-manifest.json is invalid") from exc
    return validate_manifest(raw)


def _last_modified(
    *,
    source_path: Path,
    sha256: str,
    previous_object: Mapping[str, Any] | None,
) -> str:
    if previous_object and previous_object.get("sha256") == sha256:
        value = previous_object.get("last_modified")
        if isinstance(value, str):
            return value
    return isoformat_z(datetime.fromtimestamp(source_path.stat().st_mtime, timezone.utc))


def build_snapshot(
    *,
    repo_root: Path,
    output_root: Path,
    feed_base_url: str,
    mode: str,
    pilot_feed_file: str | None,
    canary_feed_file: str | None,
    baseline_dir: Path | None,
    state_dir: Path,
    run_id: str | None = None,
    revision: str | None = None,
    secret_values: tuple[bytes, ...] = (),
    baseline_repair_profile: str | None = None,
) -> tuple[Path, dict[str, Any]]:
    repo_root = repo_root.resolve()
    output_root = output_root.resolve()
    state_dir = state_dir.resolve()
    validate_working_state(
        repo_root=repo_root,
        feed_base_url=feed_base_url,
        mode=mode,
        pilot_feed_file=pilot_feed_file,
        baseline_dir=baseline_dir,
        secret_values=secret_values,
        production=mode == "full",
        baseline_repair_profile=baseline_repair_profile,
    )

    inventory = load_source_inventory(repo_root)
    policy = load_publication_policy(repo_root)
    specs = build_object_specs(repo_root, inventory, policy)
    routes = expected_routes(
        specs=specs,
        mode=mode,
        pilot_feed_file=pilot_feed_file,
    )
    if mode == "pilot":
        canary_feed_file = pilot_feed_file
    if not canary_feed_file:
        raise ConfigurationError("a canary feed is required")
    canary_path = f"/feeds/{canary_feed_file}"
    if canary_path not in routes:
        raise ConfigurationError("canary feed is not in the publication route allowlist")

    created_at = utc_now()
    resolved_revision = source_revision(repo_root, revision)
    resolved_run_id = run_id or default_run_id(created_at, resolved_revision)
    if not SAFE_RUN_ID_RE.fullmatch(resolved_run_id):
        raise ConfigurationError("run_id contains unsafe characters")

    previous_manifest = load_previous_manifest(state_dir)
    previous_objects = (
        previous_manifest.get("objects", {}) if previous_manifest else {}
    )
    output_root.mkdir(parents=True, exist_ok=True)
    final_dir = output_root / resolved_run_id
    if final_dir.exists():
        raise ConfigurationError("snapshot staging directory already exists")
    temporary_dir = Path(
        tempfile.mkdtemp(prefix=f".{resolved_run_id}-", dir=output_root)
    )

    objects: dict[str, dict[str, Any]] = {}
    try:
        for spec in specs:
            if spec.local_path.is_symlink() or not spec.local_path.is_file():
                raise SnapshotValidationError(
                    f"artifact is not a regular non-symlink file: {spec.local_path}"
                )
            data = spec.local_path.read_bytes()
            if len(data) > policy["limits"]["max_object_bytes"]:
                raise SnapshotValidationError(
                    f"artifact exceeds configured size limit: {spec.local_path}"
                )
            digest = sha256_bytes(data)
            destination = temporary_dir / spec.object_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
            previous_object = previous_objects.get(spec.object_path)
            objects[spec.object_path] = {
                "key": f"snapshots/{resolved_run_id}/{spec.object_path}",
                "content_type": spec.content_type,
                "size": len(data),
                "sha256": digest,
                "last_modified": _last_modified(
                    source_path=spec.local_path,
                    sha256=digest,
                    previous_object=(
                        previous_object
                        if isinstance(previous_object, Mapping)
                        else None
                    ),
                ),
            }

        counts = {
            "feeds": sum(path.startswith("feeds/") for path in objects),
            "history_files": sum(path.startswith("history/") for path in objects),
            "metadata_files": sum(path.startswith("metadata/") for path in objects),
            "objects": len(objects),
            "routes": len(routes),
        }
        manifest = {
            "schema_version": 1,
            "run_id": resolved_run_id,
            "created_at": isoformat_z(created_at),
            "source_revision": resolved_revision,
            "canary_path": canary_path,
            "counts": counts,
            "objects": objects,
            "routes": routes,
        }
        validate_manifest(
            manifest,
            max_object_bytes=policy["limits"]["max_object_bytes"],
            max_manifest_objects=policy["limits"]["max_manifest_objects"],
        )
        (temporary_dir / "manifest.json").write_bytes(
            canonical_json_bytes(manifest)
        )
        os.replace(temporary_dir, final_dir)
    except Exception:
        shutil.rmtree(temporary_dir, ignore_errors=True)
        raise

    validate_snapshot_directory(
        repo_root=repo_root,
        snapshot_dir=final_dir,
        feed_base_url=feed_base_url,
        mode=mode,
        pilot_feed_file=pilot_feed_file,
        secret_values=secret_values,
    )
    return final_dir, manifest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path(".private-feed-build"),
    )
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=DEFAULT_STATE_DIR,
    )
    parser.add_argument("--feed-base-url", required=True)
    parser.add_argument("--mode", choices=("pilot", "full"), required=True)
    parser.add_argument("--pilot-feed-file")
    parser.add_argument("--canary-feed-file")
    parser.add_argument("--baseline-dir", type=Path)
    parser.add_argument("--baseline-repair-profile")
    parser.add_argument("--run-id")
    parser.add_argument("--source-revision")
    parser.add_argument("--secret-env", action="append", default=[])
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    repo_root = arguments.repo_root.resolve()
    state_dir = (
        arguments.state_dir
        if arguments.state_dir.is_absolute()
        else repo_root / arguments.state_dir
    )
    output_root = (
        arguments.output_root
        if arguments.output_root.is_absolute()
        else repo_root / arguments.output_root
    )
    baseline_dir = arguments.baseline_dir
    if baseline_dir is None:
        candidate = state_dir / "baseline"
        baseline_dir = candidate if candidate.exists() else None
    secrets = secret_values_from_environment(arguments.secret_env)

    try:
        snapshot_dir, manifest = build_snapshot(
            repo_root=repo_root,
            output_root=output_root,
            feed_base_url=arguments.feed_base_url,
            mode=arguments.mode,
            pilot_feed_file=arguments.pilot_feed_file,
            canary_feed_file=arguments.canary_feed_file,
            baseline_dir=baseline_dir,
            state_dir=state_dir,
            run_id=arguments.run_id,
            revision=arguments.source_revision,
            secret_values=secrets,
            baseline_repair_profile=arguments.baseline_repair_profile,
        )
    except PublicationError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "status": "ok",
                "run_id": manifest["run_id"],
                "snapshot_dir": str(snapshot_dir),
                "objects": manifest["counts"]["objects"],
                "routes": manifest["counts"]["routes"],
                "baseline_repair_profile": arguments.baseline_repair_profile,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
