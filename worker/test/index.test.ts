import { env } from "cloudflare:workers";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import worker from "../src/index";
import type { Env } from "../src/types";
import type {
  CurrentPointer,
  SnapshotManifest,
  SnapshotObject,
} from "../src/types";

const RUN_ID = "2026-07-24T18-00-00Z-deadbee";
const FEED_PATH = "feeds/pilot_feed.xml";
const FEED_ROUTE = "/feeds/pilot_feed.xml";
const FEED_BODY = "<?xml version=\"1.0\"?><rss version=\"2.0\"><channel /></rss>";
const LAST_MODIFIED = "2026-07-24T18:00:00Z";

function authorization(
  password = "current-secret-with-enough-length",
): string {
  return `Basic ${btoa(`feed-reader:${password}`)}`;
}

async function sha256Hex(value: string): Promise<string> {
  const digest = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(value),
  );
  return [...new Uint8Array(digest)]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

async function clearBucket(): Promise<void> {
  let cursor: string | undefined;
  do {
    const result = await env.PRIVATE_FEEDS_BUCKET.list({ cursor });
    if (result.objects.length > 0) {
      await env.PRIVATE_FEEDS_BUCKET.delete(
        result.objects.map((object) => object.key),
      );
    }
    cursor = result.truncated ? result.cursor : undefined;
  } while (cursor);
}

async function seedValidSnapshot(options?: {
  omitManifest?: boolean;
  omitObject?: boolean;
  corruptManifest?: boolean;
}): Promise<{
  manifest: SnapshotManifest;
  object: SnapshotObject;
}> {
  const feedSha256 = await sha256Hex(FEED_BODY);
  const object: SnapshotObject = {
    key: `snapshots/${RUN_ID}/${FEED_PATH}`,
    content_type: "application/rss+xml; charset=utf-8",
    size: new TextEncoder().encode(FEED_BODY).byteLength,
    sha256: feedSha256,
    last_modified: LAST_MODIFIED,
  };
  const manifest: SnapshotManifest = {
    schema_version: 1,
    run_id: RUN_ID,
    created_at: LAST_MODIFIED,
    source_revision: "deadbee",
    canary_path: FEED_ROUTE,
    counts: {
      feeds: 1,
      history_files: 0,
      metadata_files: 0,
      objects: 1,
      routes: 1,
    },
    objects: {
      [FEED_PATH]: object,
    },
    routes: {
      [FEED_ROUTE]: {
        object_path: FEED_PATH,
      },
    },
  };
  const manifestBody = options?.corruptManifest
    ? "{\"schema_version\":"
    : JSON.stringify(manifest);
  const manifestSha256 = await sha256Hex(manifestBody);
  const pointer: CurrentPointer = {
    schema_version: 1,
    run_id: RUN_ID,
    manifest_key: `snapshots/${RUN_ID}/manifest.json`,
    manifest_sha256: manifestSha256,
    published_at: LAST_MODIFIED,
  };

  if (!options?.omitObject) {
    await env.PRIVATE_FEEDS_BUCKET.put(object.key, FEED_BODY, {
      httpMetadata: {
        contentType: object.content_type,
      },
      customMetadata: {
        sha256: object.sha256,
      },
    });
  }
  if (!options?.omitManifest) {
    await env.PRIVATE_FEEDS_BUCKET.put(pointer.manifest_key, manifestBody, {
      httpMetadata: {
        contentType: "application/json; charset=utf-8",
      },
      customMetadata: {
        sha256: manifestSha256,
      },
    });
  }
  await env.PRIVATE_FEEDS_BUCKET.put(
    "current.json",
    JSON.stringify(pointer),
    {
      httpMetadata: {
        contentType: "application/json; charset=utf-8",
      },
      customMetadata: {
        sha256: await sha256Hex(JSON.stringify(pointer)),
      },
    },
  );
  return { manifest, object };
}

async function replaceManifest(manifest: SnapshotManifest): Promise<void> {
  const manifestBody = JSON.stringify(manifest);
  const manifestSha256 = await sha256Hex(manifestBody);
  const manifestKey = `snapshots/${RUN_ID}/manifest.json`;
  const pointer: CurrentPointer = {
    schema_version: 1,
    run_id: RUN_ID,
    manifest_key: manifestKey,
    manifest_sha256: manifestSha256,
    published_at: LAST_MODIFIED,
  };
  const pointerBody = JSON.stringify(pointer);
  await env.PRIVATE_FEEDS_BUCKET.put(manifestKey, manifestBody, {
    customMetadata: { sha256: manifestSha256 },
  });
  await env.PRIVATE_FEEDS_BUCKET.put("current.json", pointerBody, {
    customMetadata: { sha256: await sha256Hex(pointerBody) },
  });
}

function privateRequest(
  path = FEED_ROUTE,
  init: RequestInit = {},
): Request {
  const headers = new Headers(init.headers);
  if (!headers.has("Authorization")) {
    headers.set("Authorization", authorization());
  }
  return new Request(`https://example.com${path}`, {
    ...init,
    headers,
  });
}

function dispatch(request: Request): Promise<Response> {
  return worker.fetch(request, env as Env);
}

beforeEach(clearBucket);
afterEach(clearBucket);

describe("private feed Worker", () => {
  it("authenticates before resolving methods, paths or storage", async () => {
    const request = new Request(
      "https://example.com/feeds/%252e%252e/current.json",
      { method: "POST" },
    );
    const response = await dispatch(request);

    expect(response.status).toBe(401);
    expect(response.headers.get("WWW-Authenticate")).not.toBeNull();
    expect(await response.text()).toBe("Authentication required.\n");
  });

  it("returns the same 401 for malformed, invalid and absent credentials", async () => {
    const headers = [undefined, "Basic !!!", authorization("wrong-secret")];
    const responses = await Promise.all(
      headers.map((header) =>
        dispatch(
          new Request(`https://example.com${FEED_ROUTE}`, {
            headers: header ? { Authorization: header } : undefined,
          }),
        )
      ),
    );
    const bodies = await Promise.all(responses.map((response) => response.text()));

    expect(responses.map((response) => response.status)).toEqual([401, 401, 401]);
    expect(new Set(bodies).size).toBe(1);
  });

  it("accepts both current and transition passwords", async () => {
    await seedValidSnapshot();
    const current = await dispatch(privateRequest());
    const next = await dispatch(
      privateRequest(FEED_ROUTE, {
        headers: {
          Authorization: authorization("next-secret-with-enough-length"),
        },
      }),
    );

    expect(current.status).toBe(200);
    expect(next.status).toBe(200);
    await current.text();
    await next.text();
  });

  it("serves an authenticated RSS GET with private cache headers", async () => {
    const { object } = await seedValidSnapshot();
    const response = await dispatch(privateRequest());

    expect(response.status).toBe(200);
    expect(response.headers.get("Content-Type")).toBe(object.content_type);
    expect(response.headers.get("ETag")).toBe(`"${object.sha256}"`);
    expect(response.headers.get("Last-Modified")).toBe(
      new Date(LAST_MODIFIED).toUTCString(),
    );
    expect(response.headers.get("Cache-Control")).toContain("private");
    expect(response.headers.get("CDN-Cache-Control")).toBe("no-store");
    expect(await response.text()).toBe(FEED_BODY);
  });

  it("serves HEAD with GET metadata and no body", async () => {
    const { object } = await seedValidSnapshot();
    const getResponse = await dispatch(privateRequest());
    const headResponse = await dispatch(
      privateRequest(FEED_ROUTE, { method: "HEAD" }),
    );

    expect(headResponse.status).toBe(200);
    expect(headResponse.headers.get("Content-Length")).toBeNull();
    for (const name of ["Content-Type", "ETag", "Last-Modified"]) {
      expect(headResponse.headers.get(name)).toBe(getResponse.headers.get(name));
    }
    expect(headResponse.headers.get("ETag")).toBe(`"${object.sha256}"`);
    expect(await headResponse.text()).toBe("");
    await getResponse.text();
  });

  it("returns 304 for matching ETag on GET and HEAD", async () => {
    const { object } = await seedValidSnapshot();
    const headers = { "If-None-Match": `W/"${object.sha256}"` };
    const getResponse = await dispatch(
      privateRequest(FEED_ROUTE, { headers }),
    );
    const headResponse = await dispatch(
      privateRequest(FEED_ROUTE, { method: "HEAD", headers }),
    );

    expect(getResponse.status).toBe(304);
    expect(headResponse.status).toBe(304);
    expect(await getResponse.text()).toBe("");
    expect(await headResponse.text()).toBe("");
  });

  it("returns 304 for If-Modified-Since when no ETag is supplied", async () => {
    await seedValidSnapshot();
    const response = await dispatch(
      privateRequest(FEED_ROUTE, {
        headers: {
          "If-Modified-Since": new Date(LAST_MODIFIED).toUTCString(),
        },
      }),
    );

    expect(response.status).toBe(304);
    expect(await response.text()).toBe("");
  });

  it("returns 404 only after authentication for an absent route", async () => {
    await seedValidSnapshot();
    const response = await dispatch(
      privateRequest("/feeds/unknown_feed.xml"),
    );

    expect(response.status).toBe(404);
    expect(await response.text()).toBe("Not found.\n");
  });

  it("returns 405 only after authentication", async () => {
    const response = await dispatch(
      privateRequest(FEED_ROUTE, { method: "POST" }),
    );

    expect(response.status).toBe(405);
    expect(response.headers.get("Allow")).toBe("GET, HEAD");
    expect(await response.text()).toBe("Method not allowed.\n");
  });

  it.each([
    "/feeds/../current.json",
    "/feeds/%2Fcurrent.json",
    "/feeds/%252e%252e%252fcurrent.json",
    "/feeds/pilot_feed.xml%00",
    "/history/private.json",
  ])("rejects malicious or internal path %s", async (path) => {
    await seedValidSnapshot();
    const response = await dispatch(privateRequest(path));

    expect(response.status).toBe(404);
    expect(await response.text()).toBe("Not found.\n");
  });

  it("returns generic 503 when current.json is absent", async () => {
    const response = await dispatch(privateRequest());

    expect(response.status).toBe(503);
    expect(response.headers.get("Retry-After")).toBe("60");
    expect(await response.text()).toBe("Service unavailable.\n");
  });

  it("returns generic 503 when the manifest is absent or malformed", async () => {
    await seedValidSnapshot({ omitManifest: true });
    const missing = await dispatch(privateRequest());
    await clearBucket();
    await seedValidSnapshot({ corruptManifest: true });
    const malformed = await dispatch(privateRequest());

    expect(missing.status).toBe(503);
    expect(malformed.status).toBe(503);
    expect(await missing.text()).toBe(await malformed.text());
  });

  it("returns generic 503 when current.json bytes diverge from metadata", async () => {
    await seedValidSnapshot();
    const current = await env.PRIVATE_FEEDS_BUCKET.get("current.json");
    expect(current).not.toBeNull();
    const originalMetadata = current?.customMetadata;
    await env.PRIVATE_FEEDS_BUCKET.put(
      "current.json",
      `${await current?.text()} `,
      { customMetadata: originalMetadata },
    );

    const response = await dispatch(privateRequest());
    expect(response.status).toBe(503);
    expect(await response.text()).toBe("Service unavailable.\n");
  });

  it("returns generic 503 when manifest bytes diverge from pointer hash", async () => {
    const { manifest } = await seedValidSnapshot();
    const manifestKey = `snapshots/${RUN_ID}/manifest.json`;
    const stored = await env.PRIVATE_FEEDS_BUCKET.get(manifestKey);
    expect(stored).not.toBeNull();
    const modified = {
      ...manifest,
      created_at: "2026-07-24T19:00:00Z",
    };
    await env.PRIVATE_FEEDS_BUCKET.put(
      manifestKey,
      JSON.stringify(modified),
      { customMetadata: stored?.customMetadata },
    );

    const response = await dispatch(privateRequest());
    expect(response.status).toBe(503);
    expect(await response.text()).toBe("Service unavailable.\n");
  });

  it("rejects a manifest content type that does not match its object path", async () => {
    const { manifest, object } = await seedValidSnapshot();
    manifest.objects[FEED_PATH] = {
      ...object,
      content_type: "text/html; charset=utf-8",
    };
    await replaceManifest(manifest);

    const response = await dispatch(privateRequest());
    expect(response.status).toBe(503);
    expect(await response.text()).toBe("Service unavailable.\n");
  });

  it("rejects manifest timestamps without an explicit timezone", async () => {
    const { manifest, object } = await seedValidSnapshot();
    manifest.objects[FEED_PATH] = {
      ...object,
      last_modified: "2026-07-24T18:00:00",
    };
    await replaceManifest(manifest);

    const response = await dispatch(privateRequest());
    expect(response.status).toBe(503);
    expect(await response.text()).toBe("Service unavailable.\n");
  });

  it("returns generic 503 when a declared R2 object is absent", async () => {
    await seedValidSnapshot({ omitObject: true });
    const response = await dispatch(privateRequest());

    expect(response.status).toBe(503);
    expect(await response.text()).toBe("Service unavailable.\n");
  });

  it("checks the pointer, manifest and canary on authenticated healthz", async () => {
    await seedValidSnapshot();
    const response = await dispatch(privateRequest("/healthz"));

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({
      status: "ok",
      run_id: RUN_ID,
    });
  });
});
