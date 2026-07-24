"""Shared models and storage helpers for private feed publication.

The command-line scripts use the S3-compatible R2 API. Unit tests inject an
in-memory implementation of ``ObjectStore`` so no Cloudflare resource is
required for local validation.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Protocol


CANONICAL_FEED_BASE_URL = "https://feeds.paulofehlauer.com"
CURRENT_POINTER_KEY = "current.json"
DEFAULT_ALLOWLIST_PATH = Path("config/private_publication_allowlist.json")
DEFAULT_CONFIG_PATH = Path("config/sources_config.json")
DEFAULT_STATE_DIR = Path(".private-feed-state")
SAFE_FILENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
SAFE_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
SAFE_REVISION_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
MIN_BASIC_AUTH_PASSWORD_BYTES = 24
MAX_BASIC_AUTH_PASSWORD_BYTES = 1024
MAX_BASIC_AUTH_USERNAME_BYTES = 128


class PublicationError(RuntimeError):
    """Expected failure that should stop publication without a traceback."""


class ConfigurationError(PublicationError):
    """The source configuration or explicit allowlist is invalid."""


class ManifestError(PublicationError):
    """A current pointer or snapshot manifest is invalid."""


class StorageOperationError(PublicationError):
    """An object storage operation failed."""


class PreconditionFailed(StorageOperationError):
    """A conditional object write observed an unexpected remote state."""


class BootstrapRequired(PublicationError):
    """No active remote snapshot exists and bootstrap was not authorized."""


class CanaryError(PublicationError):
    """Post-activation HTTP canaries failed."""


@dataclass(frozen=True)
class SourceInventory:
    generated_feed_files: tuple[str, ...]
    generated_history_files: tuple[str, ...]
    native_sources: tuple[Mapping[str, Any], ...]
    source_by_feed_file: Mapping[str, Mapping[str, Any]]


@dataclass(frozen=True)
class ObjectSpec:
    local_path: Path
    object_path: str
    content_type: str
    public_path: str | None
    kind: str
    publish_in_full: bool
    publish_in_pilot: bool


@dataclass(frozen=True)
class StoredObject:
    key: str
    etag: str
    size: int
    last_modified: datetime
    content_type: str
    metadata: Mapping[str, str]
    data: bytes | None = None


class ObjectStore(Protocol):
    def get(self, key: str) -> StoredObject | None:
        """Return object metadata and bytes, or ``None`` when absent."""

    def head(self, key: str) -> StoredObject | None:
        """Return object metadata without bytes, or ``None`` when absent."""

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
        """Write an object, optionally with an atomic precondition."""

    def list_keys(self, prefix: str) -> list[str]:
        """List every key under ``prefix``."""

    def delete_keys(self, keys: Iterable[str]) -> None:
        """Delete the exact keys supplied."""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def isoformat_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(
        timespec="seconds"
    ).replace("+00:00", "Z")


def parse_iso8601(value: Any, *, field: str) -> datetime:
    if not isinstance(value, str) or "T" not in value:
        raise ManifestError(f"{field} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ManifestError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ManifestError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_storage_key(key: str) -> str:
    if not isinstance(key, str) or not key or "\\" in key:
        raise ManifestError("invalid storage key")
    path = PurePosixPath(key)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ManifestError("invalid storage key")
    if len(key.encode("utf-8")) > 1024:
        raise ManifestError("storage key exceeds R2 limit")
    return key


def safe_filename(value: Any, *, field: str, suffix: str) -> str:
    if (
        not isinstance(value, str)
        or not SAFE_FILENAME_RE.fullmatch(value)
        or not value.endswith(suffix)
    ):
        raise ConfigurationError(f"invalid {field}")
    return value


def load_json_file(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"could not read JSON file: {path}") from exc


def write_json_file(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(canonical_json_bytes(value))
    os.replace(temporary, path)


def load_source_inventory(repo_root: Path) -> SourceInventory:
    config = load_json_file(repo_root / DEFAULT_CONFIG_PATH)
    if not isinstance(config, dict) or not isinstance(config.get("sources"), list):
        raise ConfigurationError("sources_config.json must contain a sources list")

    generated_feeds: list[str] = []
    generated_histories: list[str] = []
    native_sources: list[Mapping[str, Any]] = []
    source_by_feed: dict[str, Mapping[str, Any]] = {}
    seen_histories: set[str] = set()

    for raw_source in config["sources"]:
        if not isinstance(raw_source, dict):
            raise ConfigurationError("every source must be an object")
        feed_file = safe_filename(
            raw_source.get("feed_file"),
            field="feed_file",
            suffix=".xml",
        )
        history_file = safe_filename(
            raw_source.get("history_file"),
            field="history_file",
            suffix=".json",
        )
        scraper = raw_source.get("scraper")
        if not isinstance(scraper, str) or not scraper:
            raise ConfigurationError("every source must have a scraper")
        if feed_file in source_by_feed:
            raise ConfigurationError(f"duplicate feed_file: {feed_file}")
        if history_file in seen_histories:
            raise ConfigurationError(f"duplicate history_file: {history_file}")
        source_by_feed[feed_file] = raw_source
        seen_histories.add(history_file)

        if scraper == "ExistingRssScraper":
            native_sources.append(raw_source)
        else:
            generated_feeds.append(feed_file)
            generated_histories.append(history_file)

    return SourceInventory(
        generated_feed_files=tuple(sorted(generated_feeds)),
        generated_history_files=tuple(sorted(generated_histories)),
        native_sources=tuple(native_sources),
        source_by_feed_file=source_by_feed,
    )


def load_publication_policy(repo_root: Path) -> Mapping[str, Any]:
    policy = load_json_file(repo_root / DEFAULT_ALLOWLIST_PATH)
    if not isinstance(policy, dict) or policy.get("schema_version") != 1:
        raise ConfigurationError("private publication allowlist schema is invalid")

    source_policy = policy.get("source_policy")
    if (
        not isinstance(source_policy, dict)
        or source_policy.get("include_configured_sources") is not True
        or source_policy.get("excluded_scrapers") != ["ExistingRssScraper"]
    ):
        raise ConfigurationError("source publication policy is invalid")
    if policy.get("aggregate_feed_files") != []:
        raise ConfigurationError(
            "aggregate feeds require a separate, explicit implementation decision"
        )
    if policy.get("publish_index_html") is not False:
        raise ConfigurationError("the private HTML index is disabled by policy")

    limits = policy.get("limits")
    if (
        not isinstance(limits, dict)
        or not isinstance(limits.get("max_object_bytes"), int)
        or not 0 < limits["max_object_bytes"] <= 100 * 1024 * 1024
        or not isinstance(limits.get("max_manifest_objects"), int)
        or not 0 < limits["max_manifest_objects"] <= 1000
    ):
        raise ConfigurationError("publication limits are invalid")

    metadata = policy.get("metadata")
    if not isinstance(metadata, list) or not metadata:
        raise ConfigurationError("metadata allowlist must not be empty")
    for entry in metadata:
        if not isinstance(entry, dict):
            raise ConfigurationError("metadata allowlist entries must be objects")
        local_path = entry.get("local_path")
        object_path = entry.get("object_path")
        public_path = entry.get("public_path")
        content_type = entry.get("content_type")
        publish_in_full = entry.get("publish_in_full")
        publish_in_pilot = entry.get("publish_in_pilot")
        if (
            not isinstance(local_path, str)
            or not isinstance(object_path, str)
            or not isinstance(public_path, str)
            or not isinstance(content_type, str)
            or not isinstance(publish_in_full, bool)
            or not isinstance(publish_in_pilot, bool)
        ):
            raise ConfigurationError("metadata allowlist entry is invalid")
        safe_storage_key(object_path)
        if Path(local_path).is_absolute() or ".." in Path(local_path).parts:
            raise ConfigurationError("metadata local_path is unsafe")
        if (
            not public_path.startswith("/")
            or public_path.startswith("//")
            or any(character in public_path for character in ("%", "\\", "?", "#"))
        ):
            raise ConfigurationError("metadata public_path is unsafe")
        if not content_type or len(content_type) > 128 or any(
            character in content_type for character in ("\r", "\n")
        ):
            raise ConfigurationError("metadata content_type is unsafe")
        if not publish_in_full and not publish_in_pilot:
            raise ConfigurationError(
                "metadata must be published in at least one mode"
            )
    return policy


def build_object_specs(
    repo_root: Path,
    inventory: SourceInventory,
    policy: Mapping[str, Any],
) -> tuple[ObjectSpec, ...]:
    specs: list[ObjectSpec] = []
    for feed_file in inventory.generated_feed_files:
        specs.append(
            ObjectSpec(
                local_path=repo_root / "feeds" / feed_file,
                object_path=f"feeds/{feed_file}",
                content_type="application/rss+xml; charset=utf-8",
                public_path=f"/feeds/{feed_file}",
                kind="feed",
                publish_in_full=True,
                publish_in_pilot=True,
            )
        )
    for history_file in inventory.generated_history_files:
        specs.append(
            ObjectSpec(
                local_path=repo_root / "history" / history_file,
                object_path=f"history/{history_file}",
                content_type="application/json; charset=utf-8",
                public_path=None,
                kind="history",
                publish_in_full=False,
                publish_in_pilot=False,
            )
        )
    for entry in policy["metadata"]:
        specs.append(
            ObjectSpec(
                local_path=repo_root / entry["local_path"],
                object_path=entry["object_path"],
                content_type=entry["content_type"],
                public_path=entry["public_path"],
                kind="metadata",
                publish_in_full=entry["publish_in_full"],
                publish_in_pilot=entry["publish_in_pilot"],
            )
        )

    object_paths = [spec.object_path for spec in specs]
    if len(object_paths) != len(set(object_paths)):
        raise ConfigurationError("publication object paths are not unique")
    public_paths = [
        spec.public_path for spec in specs if spec.public_path is not None
    ]
    if len(public_paths) != len(set(public_paths)):
        raise ConfigurationError("publication public paths are not unique")
    if len(specs) > policy["limits"]["max_manifest_objects"]:
        raise ConfigurationError("publication object count exceeds policy")
    return tuple(specs)


def local_path_for_object(repo_root: Path, object_path: str) -> Path:
    safe_storage_key(object_path)
    if object_path.startswith("feeds/"):
        filename = safe_filename(
            object_path.removeprefix("feeds/"),
            field="manifest feed path",
            suffix=".xml",
        )
        return repo_root / "feeds" / filename
    if object_path.startswith("history/"):
        filename = safe_filename(
            object_path.removeprefix("history/"),
            field="manifest history path",
            suffix=".json",
        )
        return repo_root / "history" / filename
    if object_path == "metadata/feeds.opml":
        return repo_root / "feeds" / "feeds.opml"
    if object_path == "metadata/index.html":
        return repo_root / "feeds" / "index.html"
    raise ManifestError("manifest contains an unsupported object path")


def validate_current_pointer(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise ManifestError("current.json schema is invalid")
    run_id = raw.get("run_id")
    manifest_key = raw.get("manifest_key")
    manifest_sha256 = raw.get("manifest_sha256")
    if not isinstance(run_id, str) or not SAFE_RUN_ID_RE.fullmatch(run_id):
        raise ManifestError("current.json run_id is invalid")
    if manifest_key != f"snapshots/{run_id}/manifest.json":
        raise ManifestError("current.json manifest_key is invalid")
    if (
        not isinstance(manifest_sha256, str)
        or not SHA256_RE.fullmatch(manifest_sha256)
    ):
        raise ManifestError("current.json manifest_sha256 is invalid")
    parse_iso8601(raw.get("published_at"), field="current.json published_at")
    return {
        "schema_version": 1,
        "run_id": run_id,
        "manifest_key": manifest_key,
        "manifest_sha256": manifest_sha256,
        "published_at": raw["published_at"],
    }


def _validate_manifest_object(
    run_id: str,
    object_path: str,
    raw: Any,
    *,
    max_object_bytes: int,
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ManifestError("manifest object entry is invalid")
    safe_storage_key(object_path)
    local_path_for_object(Path("."), object_path)
    if raw.get("key") != f"snapshots/{run_id}/{object_path}":
        raise ManifestError("manifest object key is outside its snapshot")
    content_type = raw.get("content_type")
    size = raw.get("size")
    sha256 = raw.get("sha256")
    if (
        not isinstance(content_type, str)
        or not content_type
        or len(content_type) > 128
        or any(character in content_type for character in ("\r", "\n"))
    ):
        raise ManifestError("manifest content_type is invalid")
    if not isinstance(size, int) or not 0 <= size <= max_object_bytes:
        raise ManifestError("manifest object size is invalid")
    if not isinstance(sha256, str) or not SHA256_RE.fullmatch(sha256):
        raise ManifestError("manifest object sha256 is invalid")
    parse_iso8601(raw.get("last_modified"), field="manifest last_modified")
    return {
        "key": raw["key"],
        "content_type": content_type,
        "size": size,
        "sha256": sha256,
        "last_modified": raw["last_modified"],
    }


def validate_manifest(
    raw: Any,
    *,
    expected_run_id: str | None = None,
    max_object_bytes: int = 20 * 1024 * 1024,
    max_manifest_objects: int = 1000,
) -> dict[str, Any]:
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise ManifestError("manifest schema is invalid")
    run_id = raw.get("run_id")
    if (
        not isinstance(run_id, str)
        or not SAFE_RUN_ID_RE.fullmatch(run_id)
        or (expected_run_id is not None and run_id != expected_run_id)
    ):
        raise ManifestError("manifest run_id is invalid")
    parse_iso8601(raw.get("created_at"), field="manifest created_at")
    revision = raw.get("source_revision")
    if not isinstance(revision, str) or not SAFE_REVISION_RE.fullmatch(revision):
        raise ManifestError("manifest source_revision is invalid")
    objects_raw = raw.get("objects")
    routes_raw = raw.get("routes")
    counts_raw = raw.get("counts")
    if (
        not isinstance(objects_raw, dict)
        or not 0 < len(objects_raw) <= max_manifest_objects
        or not isinstance(routes_raw, dict)
        or not 0 < len(routes_raw) <= max_manifest_objects
        or not isinstance(counts_raw, dict)
    ):
        raise ManifestError("manifest collections are invalid")

    objects = {
        object_path: _validate_manifest_object(
            run_id,
            object_path,
            entry,
            max_object_bytes=max_object_bytes,
        )
        for object_path, entry in objects_raw.items()
    }
    routes: dict[str, dict[str, str]] = {}
    feed_route_re = re.compile(r"^/feeds/[A-Za-z0-9][A-Za-z0-9._-]*\.xml$")
    for public_path, raw_route in routes_raw.items():
        if (
            not isinstance(public_path, str)
            or "%" in public_path
            or not isinstance(raw_route, dict)
            or not isinstance(raw_route.get("object_path"), str)
        ):
            raise ManifestError("manifest route is invalid")
        object_path = raw_route["object_path"]
        if object_path not in objects:
            raise ManifestError("manifest route references an absent object")
        if public_path == "/":
            expected_object_path = "metadata/index.html"
        elif public_path == "/feeds.opml":
            expected_object_path = "metadata/feeds.opml"
        elif feed_route_re.fullmatch(public_path):
            expected_object_path = public_path.removeprefix("/")
        else:
            raise ManifestError("manifest public route is not allowed")
        if object_path != expected_object_path:
            raise ManifestError("manifest route does not match object path")
        routes[public_path] = {"object_path": object_path}

    canary_path = raw.get("canary_path")
    if (
        not isinstance(canary_path, str)
        or not feed_route_re.fullmatch(canary_path)
        or canary_path not in routes
    ):
        raise ManifestError("manifest canary_path is invalid")

    expected_counts = {
        "feeds": sum(path.startswith("feeds/") for path in objects),
        "history_files": sum(path.startswith("history/") for path in objects),
        "metadata_files": sum(path.startswith("metadata/") for path in objects),
        "objects": len(objects),
        "routes": len(routes),
    }
    if counts_raw != expected_counts:
        raise ManifestError("manifest counts do not match its contents")

    return {
        "schema_version": 1,
        "run_id": run_id,
        "created_at": raw["created_at"],
        "source_revision": revision,
        "canary_path": canary_path,
        "counts": expected_counts,
        "objects": objects,
        "routes": routes,
    }


def read_manifest_bytes(
    data: bytes,
    *,
    expected_sha256: str | None = None,
    expected_run_id: str | None = None,
    max_object_bytes: int = 20 * 1024 * 1024,
    max_manifest_objects: int = 1000,
) -> dict[str, Any]:
    if expected_sha256 and sha256_bytes(data) != expected_sha256:
        raise ManifestError("manifest hash does not match current.json")
    try:
        raw = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ManifestError("manifest JSON is invalid") from exc
    return validate_manifest(
        raw,
        expected_run_id=expected_run_id,
        max_object_bytes=max_object_bytes,
        max_manifest_objects=max_manifest_objects,
    )


def read_pointer_bytes(data: bytes) -> dict[str, Any]:
    try:
        raw = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ManifestError("current.json is invalid JSON") from exc
    return validate_current_pointer(raw)


def required_environment(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ConfigurationError(f"required environment variable is missing: {name}")
    return value


def validate_basic_auth_material(username: str, password: str) -> None:
    username_bytes = username.encode("utf-8")
    password_bytes = password.encode("utf-8")
    if (
        not username_bytes
        or len(username_bytes) > MAX_BASIC_AUTH_USERNAME_BYTES
        or ":" in username
        or username != username.strip()
        or any(
            ord(character) < 0x20 or ord(character) == 0x7F
            for character in username
        )
    ):
        raise ConfigurationError("Basic Auth username is invalid")
    if not (
        MIN_BASIC_AUTH_PASSWORD_BYTES
        <= len(password_bytes)
        <= MAX_BASIC_AUTH_PASSWORD_BYTES
    ):
        raise ConfigurationError(
            "Basic Auth password does not meet the configured length policy"
        )


class S3ObjectStore:
    """Small adapter over R2's S3-compatible object API."""

    def __init__(self, client: Any, bucket: str):
        self._client = client
        self._bucket = bucket

    @classmethod
    def from_environment(cls) -> "S3ObjectStore":
        try:
            import boto3
        except ImportError as exc:
            raise ConfigurationError(
                "boto3 is required; install requirements-private.txt"
            ) from exc

        account_id = required_environment("R2_ACCOUNT_ID")
        access_key = required_environment("R2_ACCESS_KEY_ID")
        secret_key = required_environment("R2_SECRET_ACCESS_KEY")
        bucket = required_environment("R2_BUCKET")
        endpoint = f"https://{account_id}.r2.cloudflarestorage.com"
        client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name="auto",
        )
        return cls(client, bucket)

    @staticmethod
    def _etag(response: Mapping[str, Any]) -> str:
        etag = response.get("ETag")
        if not isinstance(etag, str) or not etag:
            raise StorageOperationError("R2 response did not include an ETag")
        return etag

    @staticmethod
    def _stored_object(
        key: str,
        response: Mapping[str, Any],
        *,
        data: bytes | None,
    ) -> StoredObject:
        last_modified = response.get("LastModified")
        if not isinstance(last_modified, datetime):
            last_modified = utc_now()
        metadata = response.get("Metadata")
        return StoredObject(
            key=key,
            etag=S3ObjectStore._etag(response),
            size=int(response.get("ContentLength", len(data or b""))),
            last_modified=last_modified.astimezone(timezone.utc),
            content_type=str(
                response.get("ContentType", "application/octet-stream")
            ),
            metadata=dict(metadata) if isinstance(metadata, dict) else {},
            data=data,
        )

    @staticmethod
    def _is_absent(exc: Exception) -> bool:
        response = getattr(exc, "response", {})
        error = response.get("Error", {}) if isinstance(response, dict) else {}
        metadata = (
            response.get("ResponseMetadata", {})
            if isinstance(response, dict)
            else {}
        )
        return (
            error.get("Code") in {"404", "NoSuchKey", "NotFound"}
            or metadata.get("HTTPStatusCode") == 404
        )

    @staticmethod
    def _is_precondition(exc: Exception) -> bool:
        response = getattr(exc, "response", {})
        error = response.get("Error", {}) if isinstance(response, dict) else {}
        metadata = (
            response.get("ResponseMetadata", {})
            if isinstance(response, dict)
            else {}
        )
        return (
            error.get("Code") in {"412", "PreconditionFailed"}
            or metadata.get("HTTPStatusCode") == 412
        )

    def get(self, key: str) -> StoredObject | None:
        safe_storage_key(key)
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
            body = response["Body"]
            try:
                data = body.read()
            finally:
                close = getattr(body, "close", None)
                if callable(close):
                    close()
            return self._stored_object(key, response, data=data)
        except Exception as exc:
            if self._is_absent(exc):
                return None
            raise StorageOperationError("R2 get operation failed") from None

    def head(self, key: str) -> StoredObject | None:
        safe_storage_key(key)
        try:
            response = self._client.head_object(Bucket=self._bucket, Key=key)
            return self._stored_object(key, response, data=None)
        except Exception as exc:
            if self._is_absent(exc):
                return None
            raise StorageOperationError("R2 head operation failed") from None

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
        safe_storage_key(key)
        if if_match and if_none_match:
            raise StorageOperationError("conflicting write preconditions")
        md5 = hashlib.md5(data, usedforsecurity=False).digest()
        arguments: dict[str, Any] = {
            "Bucket": self._bucket,
            "Key": key,
            "Body": data,
            "ContentType": content_type,
            "CacheControl": "private, no-cache, max-age=0",
            "ContentMD5": base64.b64encode(md5).decode("ascii"),
            "Metadata": dict(metadata),
        }
        if if_match:
            arguments["IfMatch"] = if_match
        if if_none_match:
            arguments["IfNoneMatch"] = "*"
        try:
            response = self._client.put_object(**arguments)
        except Exception as exc:
            if self._is_precondition(exc):
                raise PreconditionFailed("R2 write precondition failed") from None
            raise StorageOperationError("R2 put operation failed") from None
        head = self.head(key)
        if head is None:
            raise StorageOperationError("R2 object was absent after upload")
        return head

    def list_keys(self, prefix: str) -> list[str]:
        if prefix:
            safe_storage_key(prefix.rstrip("/"))
        keys: list[str] = []
        continuation: str | None = None
        try:
            while True:
                arguments: dict[str, Any] = {
                    "Bucket": self._bucket,
                    "Prefix": prefix,
                    "MaxKeys": 1000,
                }
                if continuation:
                    arguments["ContinuationToken"] = continuation
                response = self._client.list_objects_v2(**arguments)
                for entry in response.get("Contents", []):
                    key = entry.get("Key")
                    if isinstance(key, str):
                        keys.append(key)
                if not response.get("IsTruncated"):
                    break
                continuation = response.get("NextContinuationToken")
                if not isinstance(continuation, str):
                    raise StorageOperationError("R2 listing cursor is invalid")
        except StorageOperationError:
            raise
        except Exception:
            raise StorageOperationError("R2 list operation failed") from None
        return sorted(keys)

    def delete_keys(self, keys: Iterable[str]) -> None:
        all_keys = list(keys)
        for key in all_keys:
            safe_storage_key(key)
        try:
            for offset in range(0, len(all_keys), 1000):
                batch = all_keys[offset : offset + 1000]
                if batch:
                    response = self._client.delete_objects(
                        Bucket=self._bucket,
                        Delete={"Objects": [{"Key": key} for key in batch]},
                    )
                    errors = response.get("Errors", [])
                    if errors:
                        raise StorageOperationError(
                            "R2 reported one or more object deletion failures"
                        )
        except StorageOperationError:
            raise
        except Exception:
            raise StorageOperationError("R2 delete operation failed") from None


def load_active_remote_state(
    store: ObjectStore,
    *,
    policy: Mapping[str, Any],
) -> tuple[StoredObject, dict[str, Any], StoredObject, dict[str, Any]] | None:
    current_object = store.get(CURRENT_POINTER_KEY)
    if current_object is None:
        return None
    if current_object.data is None:
        raise StorageOperationError("current.json body was not returned")
    current_sha256 = sha256_bytes(current_object.data)
    if current_object.metadata.get("sha256") != current_sha256:
        raise ManifestError("current.json metadata hash is invalid")
    pointer = read_pointer_bytes(current_object.data)
    manifest_object = store.get(pointer["manifest_key"])
    if manifest_object is None or manifest_object.data is None:
        raise ManifestError("active manifest is absent")
    manifest = read_manifest_bytes(
        manifest_object.data,
        expected_sha256=pointer["manifest_sha256"],
        expected_run_id=pointer["run_id"],
        max_object_bytes=policy["limits"]["max_object_bytes"],
        max_manifest_objects=policy["limits"]["max_manifest_objects"],
    )
    if manifest_object.metadata.get("sha256") != pointer["manifest_sha256"]:
        raise ManifestError("active manifest metadata hash is invalid")
    return current_object, pointer, manifest_object, manifest


def secret_values_from_environment(names: Iterable[str]) -> tuple[bytes, ...]:
    values: list[bytes] = []
    for name in names:
        value = os.environ.get(name)
        if value:
            values.append(value.encode("utf-8"))
    return tuple(values)
