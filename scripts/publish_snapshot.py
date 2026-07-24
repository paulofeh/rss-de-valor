"""Upload, atomically activate, canary and retain an R2 snapshot."""

from __future__ import annotations

import argparse
import base64
import json
import sys
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import (
    HTTPRedirectHandler,
    Request,
    build_opener,
)
from xml.etree import ElementTree as ET

try:
    from .private_feed_common import (
        CURRENT_POINTER_KEY,
        DEFAULT_STATE_DIR,
        CanaryError,
        ConfigurationError,
        ManifestError,
        ObjectStore,
        PreconditionFailed,
        PublicationError,
        S3ObjectStore,
        SHA256_RE,
        StoredObject,
        StorageOperationError,
        canonical_json_bytes,
        isoformat_z,
        load_active_remote_state,
        load_publication_policy,
        read_manifest_bytes,
        read_pointer_bytes,
        required_environment,
        secret_values_from_environment,
        sha256_bytes,
        utc_now,
        validate_basic_auth_material,
    )
    from .validate_snapshot import validate_snapshot_directory
except ImportError:  # pragma: no cover - direct script execution
    from private_feed_common import (  # type: ignore[no-redef]
        CURRENT_POINTER_KEY,
        DEFAULT_STATE_DIR,
        CanaryError,
        ConfigurationError,
        ManifestError,
        ObjectStore,
        PreconditionFailed,
        PublicationError,
        S3ObjectStore,
        SHA256_RE,
        StoredObject,
        StorageOperationError,
        canonical_json_bytes,
        isoformat_z,
        load_active_remote_state,
        load_publication_policy,
        read_manifest_bytes,
        read_pointer_bytes,
        required_environment,
        secret_values_from_environment,
        sha256_bytes,
        utc_now,
        validate_basic_auth_material,
    )
    from validate_snapshot import (  # type: ignore[no-redef]
        validate_snapshot_directory,
    )


class ConcurrentPublicationError(PublicationError):
    """The remote pointer changed since hydration."""


class _NoRedirects(HTTPRedirectHandler):
    def redirect_request(
        self,
        request: Request,
        file_pointer: Any,
        code: int,
        message: str,
        headers: Any,
        new_url: str,
    ) -> None:
        return None


@dataclass(frozen=True)
class HttpResult:
    status: int
    headers: Mapping[str, str]
    body: bytes


def _http_request(
    *,
    endpoint: str,
    path: str,
    method: str,
    username: str | None,
    password: str | None,
    headers: Mapping[str, str] | None = None,
    timeout: int = 30,
) -> HttpResult:
    request_headers = dict(headers or {})
    if username is not None and password is not None:
        token = base64.b64encode(
            f"{username}:{password}".encode("utf-8")
        ).decode("ascii")
        request_headers["Authorization"] = f"Basic {token}"
    request = Request(
        f"{endpoint.rstrip('/')}{path}",
        method=method,
        headers=request_headers,
    )
    opener = build_opener(_NoRedirects)
    try:
        with opener.open(request, timeout=timeout) as response:
            return HttpResult(
                status=response.status,
                headers={
                    key.lower(): value for key, value in response.headers.items()
                },
                body=response.read(),
            )
    except HTTPError as exc:
        return HttpResult(
            status=exc.code,
            headers={
                key.lower(): value for key, value in exc.headers.items()
            },
            body=exc.read(),
        )
    except (OSError, URLError) as exc:
        raise CanaryError("private endpoint request failed") from None


def _validate_endpoint(endpoint: str) -> str:
    try:
        parsed = urlsplit(endpoint)
        port = parsed.port
    except ValueError as exc:
        raise ConfigurationError("private endpoint is invalid") from exc
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
        raise ConfigurationError(
            "private endpoint must be a credential-free HTTPS origin"
        )
    return endpoint.rstrip("/")


def run_http_canaries(
    *,
    endpoint: str,
    username: str,
    password: str,
    manifest: Mapping[str, Any],
) -> None:
    endpoint = _validate_endpoint(endpoint)
    canary_path = manifest["canary_path"]
    expected_run_id = manifest["run_id"]

    anonymous = _http_request(
        endpoint=endpoint,
        path=canary_path,
        method="GET",
        username=None,
        password=None,
    )
    challenge = anonymous.headers.get("www-authenticate", "")
    if (
        anonymous.status != 401
        or not challenge.lower().startswith("basic ")
        or anonymous.headers.get("etag")
        or anonymous.headers.get("last-modified")
        or anonymous.headers.get("content-type", "").lower().startswith(
            "application/rss+xml"
        )
    ):
        raise CanaryError("anonymous canary did not receive the Basic challenge")

    invalid = _http_request(
        endpoint=endpoint,
        path=canary_path,
        method="GET",
        username=username,
        password=f"{password}-invalid",
    )
    if (
        invalid.status != 401
        or invalid.headers.get("www-authenticate") != challenge
        or invalid.body != anonymous.body
    ):
        raise CanaryError(
            "invalid credentials did not receive the same generic 401"
        )

    authenticated = _http_request(
        endpoint=endpoint,
        path=canary_path,
        method="GET",
        username=username,
        password=password,
    )
    if authenticated.status != 200:
        raise CanaryError("authenticated feed canary did not return 200")
    if not authenticated.headers.get("content-type", "").lower().startswith(
        "application/rss+xml"
    ):
        raise CanaryError("authenticated feed canary content type is invalid")
    route = manifest["routes"].get(canary_path)
    if not isinstance(route, Mapping):
        raise CanaryError("canary route is absent from the manifest")
    expected_object = manifest["objects"].get(route.get("object_path"))
    if not isinstance(expected_object, Mapping):
        raise CanaryError("canary object is absent from the manifest")
    expected_etag = f'"{expected_object["sha256"]}"'
    if (
        authenticated.headers.get("etag") != expected_etag
        or authenticated.headers.get("content-type")
        != expected_object["content_type"]
        or authenticated.headers.get("content-length")
        != str(expected_object["size"])
        or len(authenticated.body) != expected_object["size"]
        or sha256_bytes(authenticated.body) != expected_object["sha256"]
    ):
        raise CanaryError("authenticated feed canary metadata or hash diverged")
    try:
        response_modified = parsedate_to_datetime(
            authenticated.headers["last-modified"]
        )
        manifest_modified = datetime.fromisoformat(
            str(expected_object["last_modified"]).replace("Z", "+00:00")
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise CanaryError("authenticated feed Last-Modified is invalid") from exc
    if int(response_modified.timestamp()) != int(manifest_modified.timestamp()):
        raise CanaryError("authenticated feed Last-Modified diverged")
    if (
        "private" not in authenticated.headers.get("cache-control", "").lower()
        or "authorization"
        not in authenticated.headers.get("vary", "").lower()
    ):
        raise CanaryError("authenticated feed cache policy is unsafe")
    try:
        if ET.fromstring(authenticated.body).tag != "rss":
            raise CanaryError("authenticated feed canary root is not RSS")
    except ET.ParseError as exc:
        raise CanaryError("authenticated feed canary XML is invalid") from exc

    head = _http_request(
        endpoint=endpoint,
        path=canary_path,
        method="HEAD",
        username=username,
        password=password,
    )
    etag = head.headers.get("etag")
    if (
        head.status != 200
        or head.body
        or etag != expected_etag
        or head.headers.get("content-type")
        != authenticated.headers.get("content-type")
        or head.headers.get("content-length")
        != authenticated.headers.get("content-length")
        or head.headers.get("last-modified")
        != authenticated.headers.get("last-modified")
    ):
        raise CanaryError("authenticated HEAD canary failed")

    conditional = _http_request(
        endpoint=endpoint,
        path=canary_path,
        method="GET",
        username=username,
        password=password,
        headers={"If-None-Match": etag},
    )
    if conditional.status != 304 or conditional.body:
        raise CanaryError("conditional feed canary did not return an empty 304")

    health = _http_request(
        endpoint=endpoint,
        path="/healthz",
        method="GET",
        username=username,
        password=password,
    )
    try:
        health_body = json.loads(health.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CanaryError("health canary returned invalid JSON") from exc
    if (
        health.status != 200
        or health_body != {"status": "ok", "run_id": expected_run_id}
    ):
        raise CanaryError("health canary does not match the activated snapshot")


CanaryRunner = Callable[[Mapping[str, Any]], None]


def _load_hydration_state(state_dir: Path) -> dict[str, Any]:
    path = state_dir / "hydration.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConcurrentPublicationError(
            "local hydration evidence is absent or invalid"
        ) from exc
    if (
        not isinstance(raw, dict)
        or raw.get("schema_version") != 1
        or not isinstance(raw.get("bootstrap"), bool)
    ):
        raise ConcurrentPublicationError("local hydration evidence is invalid")
    if raw["bootstrap"]:
        if (
            raw.get("observed_current_etag") is not None
            or raw.get("observed_current_sha256") is not None
            or raw.get("run_id") is not None
        ):
            raise ConcurrentPublicationError("bootstrap hydration evidence is invalid")
    else:
        if (
            not isinstance(raw.get("observed_current_etag"), str)
            or not isinstance(raw.get("observed_current_sha256"), str)
            or not isinstance(raw.get("run_id"), str)
        ):
            raise ConcurrentPublicationError("hydration evidence is incomplete")
    return raw


def _assert_expected_current(
    *,
    store: ObjectStore,
    hydration: Mapping[str, Any],
) -> StoredObject | None:
    current = store.get(CURRENT_POINTER_KEY)
    if hydration["bootstrap"]:
        if current is not None:
            raise ConcurrentPublicationError(
                "current.json appeared after bootstrap hydration"
            )
        return None
    if current is None or current.data is None:
        raise ConcurrentPublicationError("current.json disappeared after hydration")
    if (
        current.etag != hydration["observed_current_etag"]
        or sha256_bytes(current.data) != hydration["observed_current_sha256"]
        or current.metadata.get("sha256") != hydration["observed_current_sha256"]
    ):
        raise ConcurrentPublicationError("current.json changed after hydration")
    pointer = read_pointer_bytes(current.data)
    if pointer["run_id"] != hydration["run_id"]:
        raise ConcurrentPublicationError("hydrated run_id no longer matches R2")
    return current


def _put_immutable(
    *,
    store: ObjectStore,
    key: str,
    data: bytes,
    content_type: str,
    sha256: str,
) -> None:
    try:
        store.put(
            key,
            data,
            content_type=content_type,
            metadata={"sha256": sha256},
            if_none_match=True,
        )
        return
    except PreconditionFailed:
        existing = store.get(key)
        if (
            existing is None
            or existing.data is None
            or existing.size != len(data)
            or existing.metadata.get("sha256") != sha256
            or sha256_bytes(existing.data) != sha256
        ):
            raise StorageOperationError(
                "immutable snapshot key already contains different content"
            ) from None


def upload_and_verify_snapshot(
    *,
    store: ObjectStore,
    snapshot_dir: Path,
    manifest: Mapping[str, Any],
) -> tuple[bytes, str]:
    run_id = manifest["run_id"]
    for object_path, entry in sorted(manifest["objects"].items()):
        local_path = snapshot_dir / object_path
        if local_path.is_symlink() or not local_path.is_file():
            raise ManifestError(
                "staged object is not a regular non-symlink file"
            )
        data = local_path.read_bytes()
        if len(data) != entry["size"] or sha256_bytes(data) != entry["sha256"]:
            raise ManifestError("staged object changed after local validation")
        _put_immutable(
            store=store,
            key=entry["key"],
            data=data,
            content_type=entry["content_type"],
            sha256=entry["sha256"],
        )

    manifest_path = snapshot_dir / "manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ManifestError(
            "staged manifest is not a regular non-symlink file"
        )
    manifest_bytes = manifest_path.read_bytes()
    if manifest_bytes != canonical_json_bytes(manifest):
        raise ManifestError(
            "staged manifest changed or is not canonical after local validation"
        )
    manifest_sha256 = sha256_bytes(manifest_bytes)
    manifest_key = f"snapshots/{run_id}/manifest.json"
    _put_immutable(
        store=store,
        key=manifest_key,
        data=manifest_bytes,
        content_type="application/json; charset=utf-8",
        sha256=manifest_sha256,
    )

    expected_keys = {
        entry["key"] for entry in manifest["objects"].values()
    } | {manifest_key}
    actual_keys = set(store.list_keys(f"snapshots/{run_id}/"))
    if actual_keys != expected_keys:
        raise StorageOperationError(
            "remote snapshot object count differs from manifest"
        )

    # The repository's snapshot is small enough to verify every uploaded byte,
    # rather than relying on a sample.
    for object_path, entry in manifest["objects"].items():
        remote = store.get(entry["key"])
        if (
            remote is None
            or remote.data is None
            or remote.size != entry["size"]
            or remote.metadata.get("sha256") != entry["sha256"]
            or sha256_bytes(remote.data) != entry["sha256"]
        ):
            raise StorageOperationError("remote snapshot verification failed")
    remote_manifest = store.get(manifest_key)
    if (
        remote_manifest is None
        or remote_manifest.data is None
        or remote_manifest.metadata.get("sha256") != manifest_sha256
        or sha256_bytes(remote_manifest.data) != manifest_sha256
    ):
        raise StorageOperationError("remote manifest verification failed")
    return manifest_bytes, manifest_sha256


def _activate_pointer(
    *,
    store: ObjectStore,
    manifest: Mapping[str, Any],
    manifest_sha256: str,
    expected_current: StoredObject | None,
) -> tuple[StoredObject, bytes]:
    pointer = {
        "schema_version": 1,
        "run_id": manifest["run_id"],
        "manifest_key": f"snapshots/{manifest['run_id']}/manifest.json",
        "manifest_sha256": manifest_sha256,
        "published_at": isoformat_z(utc_now()),
    }
    pointer_bytes = canonical_json_bytes(pointer)
    try:
        activated = store.put(
            CURRENT_POINTER_KEY,
            pointer_bytes,
            content_type="application/json; charset=utf-8",
            metadata={"sha256": sha256_bytes(pointer_bytes)},
            if_match=(expected_current.etag if expected_current else None),
            if_none_match=expected_current is None,
        )
    except PreconditionFailed as exc:
        raise ConcurrentPublicationError(
            "current.json changed during activation"
        ) from exc
    confirmed = store.get(CURRENT_POINTER_KEY)
    if (
        confirmed is None
        or confirmed.data is None
        or confirmed.etag != activated.etag
        or confirmed.data != pointer_bytes
        or confirmed.metadata.get("sha256") != sha256_bytes(pointer_bytes)
    ):
        raise StorageOperationError("activated current.json could not be confirmed")
    return activated, pointer_bytes


def _restore_previous_pointer(
    *,
    store: ObjectStore,
    activated_etag: str,
    previous_current: StoredObject | None,
) -> None:
    if previous_current is not None:
        if previous_current.data is None:
            raise StorageOperationError("previous current.json body is unavailable")
        store.put(
            CURRENT_POINTER_KEY,
            previous_current.data,
            content_type=previous_current.content_type,
            metadata=dict(previous_current.metadata),
            if_match=activated_etag,
        )
        restored = store.get(CURRENT_POINTER_KEY)
        if (
            restored is None
            or restored.data != previous_current.data
            or restored.metadata.get("sha256")
            != previous_current.metadata.get("sha256")
        ):
            raise StorageOperationError("previous current.json was not restored")
        return

    # R2 does not expose a conditional DeleteObject. The shared workflow
    # concurrency group prevents another publisher from running here; the ETag
    # is rechecked immediately before deleting the bootstrap pointer.
    current = store.head(CURRENT_POINTER_KEY)
    if current is None or current.etag != activated_etag:
        raise ConcurrentPublicationError(
            "bootstrap pointer changed before rollback"
        )
    store.delete_keys([CURRENT_POINTER_KEY])
    if store.head(CURRENT_POINTER_KEY) is not None:
        raise StorageOperationError("bootstrap pointer could not be removed")


def _load_manifest_for_pointer(
    *,
    store: ObjectStore,
    current: StoredObject | None,
    policy: Mapping[str, Any],
) -> Mapping[str, Any] | None:
    if current is None or current.data is None:
        return None
    pointer = read_pointer_bytes(current.data)
    remote_manifest = store.get(pointer["manifest_key"])
    if remote_manifest is None or remote_manifest.data is None:
        raise ManifestError("previous active manifest is unavailable")
    if remote_manifest.metadata.get("sha256") != pointer["manifest_sha256"]:
        raise ManifestError("previous active manifest metadata hash is invalid")
    return read_manifest_bytes(
        remote_manifest.data,
        expected_sha256=pointer["manifest_sha256"],
        expected_run_id=pointer["run_id"],
        max_object_bytes=policy["limits"]["max_object_bytes"],
        max_manifest_objects=policy["limits"]["max_manifest_objects"],
    )


def apply_retention(
    *,
    store: ObjectStore,
    active_run_id: str,
    previous_run_id: str | None,
    keep: int,
    policy: Mapping[str, Any],
    expected_current_etag: str | None = None,
) -> list[str]:
    if keep < 2:
        raise ConfigurationError("retention must keep at least two snapshots")
    manifest_keys = [
        key
        for key in store.list_keys("snapshots/")
        if key.endswith("/manifest.json")
    ]
    snapshots: list[tuple[datetime, str]] = []
    for key in manifest_keys:
        parts = key.split("/")
        if len(parts) != 3 or parts[0] != "snapshots":
            continue
        key_run_id = parts[1]
        remote = store.get(key)
        if remote is None or remote.data is None:
            continue
        try:
            metadata_sha256 = remote.metadata.get("sha256")
            if (
                not isinstance(metadata_sha256, str)
                or not SHA256_RE.fullmatch(metadata_sha256)
            ):
                raise ManifestError("snapshot manifest metadata hash is invalid")
            manifest = read_manifest_bytes(
                remote.data,
                expected_sha256=metadata_sha256,
                expected_run_id=key_run_id,
                max_object_bytes=policy["limits"]["max_object_bytes"],
                max_manifest_objects=policy["limits"]["max_manifest_objects"],
            )
            expected_keys = {
                entry["key"] for entry in manifest["objects"].values()
            } | {key}
            if set(store.list_keys(f"snapshots/{key_run_id}/")) != expected_keys:
                raise ManifestError("snapshot prefix is incomplete")
            for entry in manifest["objects"].values():
                stored = store.head(entry["key"])
                if (
                    stored is None
                    or stored.size != entry["size"]
                    or stored.metadata.get("sha256") != entry["sha256"]
                ):
                    raise ManifestError("snapshot object metadata is invalid")
            created_at = datetime.fromisoformat(
                manifest["created_at"].replace("Z", "+00:00")
            )
        except (ManifestError, ValueError):
            # Preserve corrupt/incomplete prefixes for diagnosis or manual
            # cleanup; retention deletes only validated complete snapshots.
            continue
        snapshots.append((created_at, manifest["run_id"]))

    if len(snapshots) <= keep:
        return []
    snapshots.sort(reverse=True)
    protected = {active_run_id}
    if previous_run_id:
        protected.add(previous_run_id)
    keep_ids = set(protected)
    for _, run_id in snapshots:
        if len(keep_ids) >= keep:
            break
        keep_ids.add(run_id)

    delete_ids = [
        run_id
        for _, run_id in snapshots
        if run_id not in keep_ids
    ]
    for run_id in delete_ids:
        current = store.get(CURRENT_POINTER_KEY)
        if current is None or current.data is None:
            raise ConcurrentPublicationError(
                "current.json disappeared during retention"
            )
        pointer = read_pointer_bytes(current.data)
        if (
            pointer["run_id"] != active_run_id
            or (
                expected_current_etag is not None
                and current.etag != expected_current_etag
            )
        ):
            raise ConcurrentPublicationError(
                "current.json changed during retention"
            )
        keys = store.list_keys(f"snapshots/{run_id}/")
        store.delete_keys(keys)
        if store.list_keys(f"snapshots/{run_id}/"):
            raise StorageOperationError(
                "retention could not remove the complete snapshot prefix"
            )
    return delete_ids


def publish_snapshot(
    *,
    store: ObjectStore,
    repo_root: Path,
    snapshot_dir: Path,
    state_dir: Path,
    feed_base_url: str,
    mode: str,
    pilot_feed_file: str | None,
    retention: int,
    canary_runner: CanaryRunner,
    secret_values: tuple[bytes, ...] = (),
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    snapshot_dir = snapshot_dir.resolve()
    state_dir = state_dir.resolve()
    policy = load_publication_policy(repo_root)
    manifest = validate_snapshot_directory(
        repo_root=repo_root,
        snapshot_dir=snapshot_dir,
        feed_base_url=feed_base_url,
        mode=mode,
        pilot_feed_file=pilot_feed_file,
        secret_values=secret_values,
    )
    hydration = _load_hydration_state(state_dir)
    previous_current = _assert_expected_current(
        store=store,
        hydration=hydration,
    )
    previous_manifest = _load_manifest_for_pointer(
        store=store,
        current=previous_current,
        policy=policy,
    )

    _, manifest_sha256 = upload_and_verify_snapshot(
        store=store,
        snapshot_dir=snapshot_dir,
        manifest=manifest,
    )
    # Re-read immediately before the atomic conditional write. The If-Match /
    # If-None-Match below is the final compare-and-swap guard.
    previous_current = _assert_expected_current(
        store=store,
        hydration=hydration,
    )
    activated, _ = _activate_pointer(
        store=store,
        manifest=manifest,
        manifest_sha256=manifest_sha256,
        expected_current=previous_current,
    )

    try:
        canary_runner(manifest)
    except Exception as exc:
        _restore_previous_pointer(
            store=store,
            activated_etag=activated.etag,
            previous_current=previous_current,
        )
        if previous_manifest is not None:
            try:
                canary_runner(previous_manifest)
            except Exception as rollback_exc:
                raise CanaryError(
                    "new snapshot failed and restored snapshot canary also failed"
                ) from rollback_exc
        raise CanaryError(
            "new snapshot failed canaries; previous pointer was restored"
        ) from exc

    previous_run_id = (
        previous_manifest["run_id"] if previous_manifest is not None else None
    )
    deleted = apply_retention(
        store=store,
        active_run_id=manifest["run_id"],
        previous_run_id=previous_run_id,
        keep=retention,
        policy=policy,
        expected_current_etag=activated.etag,
    )
    return {
        "status": "published",
        "run_id": manifest["run_id"],
        "previous_run_id": previous_run_id,
        "objects": manifest["counts"]["objects"],
        "routes": manifest["counts"]["routes"],
        "retention_deleted": deleted,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--snapshot-dir", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIR)
    parser.add_argument("--feed-base-url", required=True)
    parser.add_argument("--mode", choices=("pilot", "full"), required=True)
    parser.add_argument("--pilot-feed-file")
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--retention", type=int, default=28)
    parser.add_argument(
        "--username-env",
        default="PRIVATE_FEED_USERNAME",
    )
    parser.add_argument(
        "--password-env",
        default="PRIVATE_FEED_PASSWORD",
    )
    parser.add_argument(
        "--secret-env",
        action="append",
        default=[],
        help="Environment variable whose value must not appear in the snapshot.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    repo_root = arguments.repo_root.resolve()
    snapshot_dir = arguments.snapshot_dir
    if not snapshot_dir.is_absolute():
        snapshot_dir = repo_root / snapshot_dir
    state_dir = arguments.state_dir
    if not state_dir.is_absolute():
        state_dir = repo_root / state_dir
    try:
        username = required_environment(arguments.username_env)
        password = required_environment(arguments.password_env)
        validate_basic_auth_material(username, password)
        endpoint = _validate_endpoint(arguments.endpoint)
        if arguments.feed_base_url.rstrip("/") != endpoint:
            raise ConfigurationError(
                "FEED_BASE_URL must match the canary endpoint"
            )
        secret_names = set(arguments.secret_env)
        secret_names.update(
            {
                arguments.username_env,
                arguments.password_env,
                "R2_ACCESS_KEY_ID",
                "R2_SECRET_ACCESS_KEY",
            }
        )
        result = publish_snapshot(
            store=S3ObjectStore.from_environment(),
            repo_root=repo_root,
            snapshot_dir=snapshot_dir,
            state_dir=state_dir,
            feed_base_url=arguments.feed_base_url,
            mode=arguments.mode,
            pilot_feed_file=arguments.pilot_feed_file,
            retention=arguments.retention,
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
