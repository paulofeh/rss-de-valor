import type {
  CurrentPointer,
  SnapshotManifest,
  SnapshotObject,
  SnapshotRoute,
} from "./types";

const CURRENT_POINTER_KEY = "current.json";
const MAX_CURRENT_POINTER_BYTES = 4096;
const MAX_MANIFEST_BYTES = 1024 * 1024;
const MAX_MANIFEST_OBJECTS = 1000;
const MAX_OBJECT_BYTES = 20 * 1024 * 1024;
const SAFE_RUN_ID = /^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/u;
const SAFE_SHA256 = /^[a-f0-9]{64}$/u;
const SAFE_FEED_FILE = /^[A-Za-z0-9][A-Za-z0-9._-]*\.xml$/u;
const SAFE_HISTORY_FILE = /^[A-Za-z0-9][A-Za-z0-9._-]*\.json$/u;
const SAFE_REVISION = /^[A-Za-z0-9._-]{1,128}$/u;

export class SnapshotUnavailableError extends Error {
  constructor() {
    super("Active snapshot unavailable");
    this.name = "SnapshotUnavailableError";
  }
}

export interface ActiveSnapshot {
  pointer: CurrentPointer;
  manifest: SnapshotManifest;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isIsoDate(value: unknown): value is string {
  return (
    typeof value === "string" &&
    Number.isFinite(Date.parse(value)) &&
    value.includes("T") &&
    /(?:Z|[+-]\d{2}:\d{2})$/u.test(value)
  );
}

function isNonNegativeInteger(value: unknown): value is number {
  return Number.isInteger(value) && Number(value) >= 0;
}

function isSafeObjectPath(path: string): boolean {
  if (path.startsWith("feeds/")) {
    return SAFE_FEED_FILE.test(path.slice("feeds/".length));
  }
  if (path.startsWith("history/")) {
    return SAFE_HISTORY_FILE.test(path.slice("history/".length));
  }
  return path === "metadata/feeds.opml" || path === "metadata/index.html";
}

function expectedContentType(objectPath: string): string | null {
  if (objectPath.startsWith("feeds/")) {
    return "application/rss+xml; charset=utf-8";
  }
  if (objectPath.startsWith("history/")) {
    return "application/json; charset=utf-8";
  }
  if (objectPath === "metadata/feeds.opml") {
    return "text/x-opml; charset=utf-8";
  }
  if (objectPath === "metadata/index.html") {
    return "text/html; charset=utf-8";
  }
  return null;
}

export function isPotentialPublicPath(path: string): boolean {
  if (path === "/" || path === "/feeds.opml" || path === "/healthz") {
    return true;
  }
  return path.startsWith("/feeds/") &&
    SAFE_FEED_FILE.test(path.slice("/feeds/".length));
}

function routeMatchesObjectPath(
  publicPath: string,
  objectPath: string,
): boolean {
  if (publicPath === "/") {
    return objectPath === "metadata/index.html";
  }
  if (publicPath === "/feeds.opml") {
    return objectPath === "metadata/feeds.opml";
  }
  if (publicPath.startsWith("/feeds/")) {
    return objectPath === publicPath.slice(1);
  }
  return false;
}

function parseCurrentPointer(value: unknown): CurrentPointer | null {
  if (!isRecord(value)) {
    return null;
  }

  const runId = value.run_id;
  const manifestKey = value.manifest_key;
  if (
    value.schema_version !== 1 ||
    typeof runId !== "string" ||
    !SAFE_RUN_ID.test(runId) ||
    manifestKey !== `snapshots/${runId}/manifest.json` ||
    typeof value.manifest_sha256 !== "string" ||
    !SAFE_SHA256.test(value.manifest_sha256) ||
    !isIsoDate(value.published_at)
  ) {
    return null;
  }

  return value as unknown as CurrentPointer;
}

function parseSnapshotObject(
  value: unknown,
  runId: string,
  objectPath: string,
): SnapshotObject | null {
  if (!isRecord(value) || !isSafeObjectPath(objectPath)) {
    return null;
  }

  const expectedKey = `snapshots/${runId}/${objectPath}`;
  const contentType = expectedContentType(objectPath);
  if (
    value.key !== expectedKey ||
    value.content_type !== contentType ||
    !isNonNegativeInteger(value.size) ||
    Number(value.size) > MAX_OBJECT_BYTES ||
    typeof value.sha256 !== "string" ||
    !SAFE_SHA256.test(value.sha256) ||
    !isIsoDate(value.last_modified)
  ) {
    return null;
  }

  return value as unknown as SnapshotObject;
}

function parseSnapshotRoute(value: unknown): SnapshotRoute | null {
  if (
    !isRecord(value) ||
    typeof value.object_path !== "string" ||
    !isSafeObjectPath(value.object_path)
  ) {
    return null;
  }
  return value as unknown as SnapshotRoute;
}

function parseSnapshotManifest(
  value: unknown,
  pointer: CurrentPointer,
): SnapshotManifest | null {
  if (!isRecord(value) || !isRecord(value.counts)) {
    return null;
  }

  if (
    value.schema_version !== 1 ||
    value.run_id !== pointer.run_id ||
    !isIsoDate(value.created_at) ||
    typeof value.source_revision !== "string" ||
    !SAFE_REVISION.test(value.source_revision) ||
    typeof value.canary_path !== "string" ||
    !isRecord(value.objects) ||
    !isRecord(value.routes)
  ) {
    return null;
  }

  const objectEntries = Object.entries(value.objects);
  const routeEntries = Object.entries(value.routes);
  if (
    objectEntries.length === 0 ||
    objectEntries.length > MAX_MANIFEST_OBJECTS ||
    routeEntries.length === 0 ||
    routeEntries.length > MAX_MANIFEST_OBJECTS
  ) {
    return null;
  }

  const objects: Record<string, SnapshotObject> = {};
  for (const [objectPath, objectValue] of objectEntries) {
    const parsed = parseSnapshotObject(
      objectValue,
      pointer.run_id,
      objectPath,
    );
    if (!parsed) {
      return null;
    }
    objects[objectPath] = parsed;
  }

  const routes: Record<string, SnapshotRoute> = {};
  for (const [publicPath, routeValue] of routeEntries) {
    if (
      publicPath === "/healthz" ||
      !isPotentialPublicPath(publicPath) ||
      publicPath.includes("%")
    ) {
      return null;
    }
    const parsed = parseSnapshotRoute(routeValue);
    if (
      !parsed ||
      !objects[parsed.object_path] ||
      !routeMatchesObjectPath(publicPath, parsed.object_path)
    ) {
      return null;
    }
    routes[publicPath] = parsed;
  }

  if (
    typeof value.canary_path !== "string" ||
    !value.canary_path.startsWith("/feeds/") ||
    !routes[value.canary_path]
  ) {
    return null;
  }

  const counts = value.counts;
  const countNames = [
    "feeds",
    "history_files",
    "metadata_files",
    "objects",
    "routes",
  ] as const;
  for (const name of countNames) {
    if (!isNonNegativeInteger(counts[name])) {
      return null;
    }
  }
  if (
    counts.objects !== objectEntries.length ||
    counts.routes !== routeEntries.length
  ) {
    return null;
  }
  const feedCount = objectEntries.filter(([path]) =>
    path.startsWith("feeds/")
  ).length;
  const historyCount = objectEntries.filter(([path]) =>
    path.startsWith("history/")
  ).length;
  const metadataCount = objectEntries.filter(([path]) =>
    path.startsWith("metadata/")
  ).length;
  if (
    counts.feeds !== feedCount ||
    counts.history_files !== historyCount ||
    counts.metadata_files !== metadataCount
  ) {
    return null;
  }

  return {
    schema_version: 1,
    run_id: pointer.run_id,
    created_at: value.created_at,
    source_revision: value.source_revision,
    canary_path: value.canary_path,
    counts: {
      feeds: Number(counts.feeds),
      history_files: Number(counts.history_files),
      metadata_files: Number(counts.metadata_files),
      objects: Number(counts.objects),
      routes: Number(counts.routes),
    },
    objects,
    routes,
  };
}

async function readJsonObject(
  bucket: R2Bucket,
  key: string,
  maxBytes: number,
  expectedSha256?: string,
): Promise<unknown> {
  let object: R2ObjectBody | null;
  try {
    object = await bucket.get(key);
  } catch {
    throw new SnapshotUnavailableError();
  }
  if (!object) {
    throw new SnapshotUnavailableError();
  }
  if (object.size > maxBytes) {
    await object.body.cancel();
    throw new SnapshotUnavailableError();
  }

  try {
    const data = await object.arrayBuffer();
    const digest = await crypto.subtle.digest("SHA-256", data);
    const actualSha256 = [...new Uint8Array(digest)]
      .map((byte) => byte.toString(16).padStart(2, "0"))
      .join("");
    if (
      object.customMetadata?.sha256 !== actualSha256 ||
      (expectedSha256 !== undefined && expectedSha256 !== actualSha256)
    ) {
      throw new SnapshotUnavailableError();
    }
    return JSON.parse(new TextDecoder().decode(data)) as unknown;
  } catch {
    throw new SnapshotUnavailableError();
  }
}

export async function loadActiveSnapshot(
  bucket: R2Bucket,
): Promise<ActiveSnapshot> {
  const rawPointer = await readJsonObject(
    bucket,
    CURRENT_POINTER_KEY,
    MAX_CURRENT_POINTER_BYTES,
  );
  const pointer = parseCurrentPointer(rawPointer);
  if (!pointer) {
    throw new SnapshotUnavailableError();
  }

  const rawManifest = await readJsonObject(
    bucket,
    pointer.manifest_key,
    MAX_MANIFEST_BYTES,
    pointer.manifest_sha256,
  );
  const manifest = parseSnapshotManifest(rawManifest, pointer);
  if (!manifest) {
    throw new SnapshotUnavailableError();
  }

  return { pointer, manifest };
}

export function resolveRoute(
  manifest: SnapshotManifest,
  publicPath: string,
): SnapshotObject | null {
  const route = manifest.routes[publicPath];
  if (!route) {
    return null;
  }
  return manifest.objects[route.object_path] ?? null;
}

export function responseHeaders(object: SnapshotObject): Headers {
  const headers = new Headers({
    "Cache-Control": "private, no-cache, max-age=0, no-transform",
    "CDN-Cache-Control": "no-store",
    "Cloudflare-CDN-Cache-Control": "no-store",
    "Content-Type": object.content_type,
    "ETag": `"${object.sha256}"`,
    "Last-Modified": new Date(object.last_modified).toUTCString(),
    "Vary": "Authorization",
    "X-Content-Type-Options": "nosniff",
  });
  return headers;
}

function normalizedEtag(value: string): string {
  return value.trim().replace(/^W\//iu, "");
}

export function requestIsNotModified(
  request: Request,
  object: SnapshotObject,
): boolean {
  const etag = `"${object.sha256}"`;
  const ifNoneMatch = request.headers.get("If-None-Match");
  if (ifNoneMatch !== null) {
    return ifNoneMatch
      .split(",")
      .some((candidate) =>
        candidate.trim() === "*" ||
        normalizedEtag(candidate) === normalizedEtag(etag)
      );
  }

  const ifModifiedSince = request.headers.get("If-Modified-Since");
  if (!ifModifiedSince) {
    return false;
  }
  const conditionTime = Date.parse(ifModifiedSince);
  const objectTime = Date.parse(object.last_modified);
  if (!Number.isFinite(conditionTime) || !Number.isFinite(objectTime)) {
    return false;
  }
  return Math.floor(objectTime / 1000) <= Math.floor(conditionTime / 1000);
}

function storedObjectMatches(
  stored: R2Object,
  expected: SnapshotObject,
): boolean {
  return (
    stored.size === expected.size &&
    stored.customMetadata?.sha256 === expected.sha256
  );
}

export async function headSnapshotObject(
  bucket: R2Bucket,
  object: SnapshotObject,
): Promise<R2Object> {
  let stored: R2Object | null;
  try {
    stored = await bucket.head(object.key);
  } catch {
    throw new SnapshotUnavailableError();
  }
  if (!stored || !storedObjectMatches(stored, object)) {
    throw new SnapshotUnavailableError();
  }
  return stored;
}

export async function getSnapshotObject(
  bucket: R2Bucket,
  object: SnapshotObject,
): Promise<R2ObjectBody> {
  let stored: R2ObjectBody | null;
  try {
    stored = await bucket.get(object.key);
  } catch {
    throw new SnapshotUnavailableError();
  }
  if (!stored || !storedObjectMatches(stored, object)) {
    if (stored) {
      await stored.body.cancel();
    }
    throw new SnapshotUnavailableError();
  }
  return stored;
}
