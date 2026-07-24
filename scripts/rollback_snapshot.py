"""Atomically point R2 at a previously validated immutable snapshot."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Mapping

try:
    from .private_feed_common import (
        SAFE_RUN_ID_RE,
        CanaryError,
        ConfigurationError,
        ManifestError,
        ObjectStore,
        PublicationError,
        S3ObjectStore,
        StoredObject,
        build_object_specs,
        load_active_remote_state,
        load_publication_policy,
        load_source_inventory,
        read_manifest_bytes,
        required_environment,
        secret_values_from_environment,
        sha256_bytes,
        validate_basic_auth_material,
    )
    from .publish_snapshot import (
        ConcurrentPublicationError,
        _activate_pointer,
        _restore_previous_pointer,
        _validate_endpoint,
        run_http_canaries,
    )
    from .validate_snapshot import expected_routes, validate_snapshot_directory
except ImportError:  # pragma: no cover - direct script execution
    from private_feed_common import (  # type: ignore[no-redef]
        SAFE_RUN_ID_RE,
        CanaryError,
        ConfigurationError,
        ManifestError,
        ObjectStore,
        PublicationError,
        S3ObjectStore,
        StoredObject,
        build_object_specs,
        load_active_remote_state,
        load_publication_policy,
        load_source_inventory,
        read_manifest_bytes,
        required_environment,
        secret_values_from_environment,
        sha256_bytes,
        validate_basic_auth_material,
    )
    from publish_snapshot import (  # type: ignore[no-redef]
        ConcurrentPublicationError,
        _activate_pointer,
        _restore_previous_pointer,
        _validate_endpoint,
        run_http_canaries,
    )
    from validate_snapshot import (  # type: ignore[no-redef]
        expected_routes,
        validate_snapshot_directory,
    )


RollbackCanaryRunner = Callable[[Mapping[str, Any]], None]


def _load_complete_target(
    *,
    store: ObjectStore,
    repo_root: Path,
    target_run_id: str,
    required_mode: str,
    feed_base_url: str,
    secret_values: tuple[bytes, ...],
) -> tuple[Mapping[str, Any], str]:
    if not SAFE_RUN_ID_RE.fullmatch(target_run_id):
        raise ConfigurationError("target run_id contains unsafe characters")

    policy = load_publication_policy(repo_root)
    inventory = load_source_inventory(repo_root)
    specs = build_object_specs(repo_root, inventory, policy)
    manifest_key = f"snapshots/{target_run_id}/manifest.json"
    remote_manifest = store.get(manifest_key)
    if remote_manifest is None or remote_manifest.data is None:
        raise ManifestError("rollback target manifest is absent")

    manifest_sha256 = sha256_bytes(remote_manifest.data)
    if remote_manifest.metadata.get("sha256") != manifest_sha256:
        raise ManifestError("rollback target manifest metadata hash is invalid")
    manifest = read_manifest_bytes(
        remote_manifest.data,
        expected_sha256=manifest_sha256,
        expected_run_id=target_run_id,
        max_object_bytes=policy["limits"]["max_object_bytes"],
        max_manifest_objects=policy["limits"]["max_manifest_objects"],
    )

    expected_object_paths = {spec.object_path for spec in specs}
    if set(manifest["objects"]) != expected_object_paths:
        raise ManifestError(
            "rollback target object allowlist does not match source configuration"
        )

    full_routes = expected_routes(
        specs=specs,
        mode="full",
        pilot_feed_file=None,
    )
    route_feed_files = [
        path.removeprefix("/feeds/")
        for path in manifest["routes"]
        if path.startswith("/feeds/")
    ]
    is_valid_pilot = (
        len(manifest["routes"]) == 1
        and len(route_feed_files) == 1
        and manifest["routes"]
        == expected_routes(
            specs=specs,
            mode="pilot",
            pilot_feed_file=route_feed_files[0],
        )
    )
    detected_mode = (
        "full"
        if manifest["routes"] == full_routes
        else "pilot"
        if is_valid_pilot
        else None
    )
    if detected_mode is None:
        raise ManifestError("rollback target route allowlist is invalid")
    if detected_mode != required_mode:
        raise ManifestError(
            "rollback target publication mode does not match this environment"
        )

    expected_keys = {
        entry["key"] for entry in manifest["objects"].values()
    } | {manifest_key}
    if set(store.list_keys(f"snapshots/{target_run_id}/")) != expected_keys:
        raise ManifestError("rollback target snapshot prefix is incomplete")

    downloaded: dict[str, bytes] = {}
    for object_path, entry in manifest["objects"].items():
        remote = store.get(entry["key"])
        if (
            remote is None
            or remote.data is None
            or remote.size != entry["size"]
            or len(remote.data) != entry["size"]
            or remote.metadata.get("sha256") != entry["sha256"]
            or sha256_bytes(remote.data) != entry["sha256"]
        ):
            raise ManifestError("rollback target object hash or size diverged")
        downloaded[object_path] = remote.data

    pilot_feed_file = route_feed_files[0] if detected_mode == "pilot" else None
    with tempfile.TemporaryDirectory(prefix="private-feed-rollback-") as temporary:
        snapshot_dir = Path(temporary)
        for object_path, data in downloaded.items():
            destination = snapshot_dir / object_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
        (snapshot_dir / "manifest.json").write_bytes(remote_manifest.data)
        validate_snapshot_directory(
            repo_root=repo_root,
            snapshot_dir=snapshot_dir,
            feed_base_url=feed_base_url,
            mode=required_mode,
            pilot_feed_file=pilot_feed_file,
            secret_values=secret_values,
        )

    return manifest, manifest_sha256


def _same_current(
    left: StoredObject,
    right: StoredObject,
) -> bool:
    return (
        left.etag == right.etag
        and left.data is not None
        and right.data is not None
        and left.data == right.data
    )


def rollback_snapshot(
    *,
    store: ObjectStore,
    repo_root: Path,
    target_run_id: str,
    required_mode: str,
    feed_base_url: str,
    canary_runner: RollbackCanaryRunner,
    secret_values: tuple[bytes, ...] = (),
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    policy = load_publication_policy(repo_root)
    active = load_active_remote_state(store, policy=policy)
    if active is None:
        raise ManifestError("current.json is absent; there is nothing to roll back")
    previous_current, previous_pointer, _, previous_manifest = active

    target_manifest, target_manifest_sha256 = _load_complete_target(
        store=store,
        repo_root=repo_root,
        target_run_id=target_run_id,
        required_mode=required_mode,
        feed_base_url=feed_base_url,
        secret_values=secret_values,
    )
    current_before_activation = store.get("current.json")
    if (
        current_before_activation is None
        or not _same_current(current_before_activation, previous_current)
    ):
        raise ConcurrentPublicationError(
            "current.json changed while the rollback target was validated"
        )

    if target_run_id == previous_pointer["run_id"]:
        canary_runner(target_manifest)
        return {
            "status": "already-active",
            "run_id": target_run_id,
            "previous_run_id": target_run_id,
        }

    activated, _ = _activate_pointer(
        store=store,
        manifest=target_manifest,
        manifest_sha256=target_manifest_sha256,
        expected_current=current_before_activation,
    )
    try:
        canary_runner(target_manifest)
    except Exception as exc:
        _restore_previous_pointer(
            store=store,
            activated_etag=activated.etag,
            previous_current=previous_current,
        )
        try:
            canary_runner(previous_manifest)
        except Exception as restored_exc:
            raise CanaryError(
                "rollback target failed and restored snapshot canary also failed"
            ) from restored_exc
        raise CanaryError(
            "rollback target failed canaries; original pointer was restored"
        ) from exc

    return {
        "status": "rolled-back",
        "run_id": target_run_id,
        "previous_run_id": previous_pointer["run_id"],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--target-run-id", required=True)
    parser.add_argument(
        "--required-mode",
        choices=("pilot", "full"),
        required=True,
    )
    parser.add_argument("--endpoint", required=True)
    parser.add_argument(
        "--username-env",
        default="PRIVATE_FEED_USERNAME",
    )
    parser.add_argument(
        "--password-env",
        default="PRIVATE_FEED_PASSWORD",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    repo_root = arguments.repo_root.resolve()
    try:
        username = required_environment(arguments.username_env)
        password = required_environment(arguments.password_env)
        validate_basic_auth_material(username, password)
        endpoint = _validate_endpoint(arguments.endpoint)
        secret_names = {
            arguments.username_env,
            arguments.password_env,
            "R2_ACCESS_KEY_ID",
            "R2_SECRET_ACCESS_KEY",
        }
        result = rollback_snapshot(
            store=S3ObjectStore.from_environment(),
            repo_root=repo_root,
            target_run_id=arguments.target_run_id,
            required_mode=arguments.required_mode,
            feed_base_url=endpoint,
            secret_values=secret_values_from_environment(sorted(secret_names)),
            canary_runner=lambda manifest: run_http_canaries(
                endpoint=endpoint,
                username=username,
                password=password,
                manifest=manifest,
            ),
        )
    except PublicationError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
