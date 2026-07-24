import { isAuthorized, unauthorizedResponse } from "./auth";
import {
  getSnapshotObject,
  headSnapshotObject,
  isPotentialPublicPath,
  loadActiveSnapshot,
  requestIsNotModified,
  resolveRoute,
  responseHeaders,
  SnapshotUnavailableError,
} from "./storage";
import type { Env, SnapshotObject } from "./types";

function genericTextResponse(status: number, body: string): Response {
  return new Response(body, {
    status,
    headers: {
      "Cache-Control": "no-store",
      "CDN-Cache-Control": "no-store",
      "Cloudflare-CDN-Cache-Control": "no-store",
      "Content-Type": "text/plain; charset=utf-8",
      "Vary": "Authorization",
      "X-Content-Type-Options": "nosniff",
    },
  });
}

function notFoundResponse(): Response {
  return genericTextResponse(404, "Not found.\n");
}

function methodNotAllowedResponse(): Response {
  const response = genericTextResponse(405, "Method not allowed.\n");
  response.headers.set("Allow", "GET, HEAD");
  return response;
}

function unavailableResponse(): Response {
  const response = genericTextResponse(503, "Service unavailable.\n");
  response.headers.set("Retry-After", "60");
  return response;
}

async function healthResponse(
  request: Request,
  env: Env,
): Promise<Response> {
  const active = await loadActiveSnapshot(env.PRIVATE_FEEDS_BUCKET);
  const canary = resolveRoute(
    active.manifest,
    active.manifest.canary_path,
  );
  if (!canary) {
    throw new SnapshotUnavailableError();
  }
  await headSnapshotObject(env.PRIVATE_FEEDS_BUCKET, canary);

  const body = JSON.stringify({
    status: "ok",
    run_id: active.pointer.run_id,
  });
  const headers = new Headers({
    "Cache-Control": "no-store",
    "CDN-Cache-Control": "no-store",
    "Cloudflare-CDN-Cache-Control": "no-store",
    "Content-Type": "application/json; charset=utf-8",
    "Vary": "Authorization",
    "X-Content-Type-Options": "nosniff",
  });
  if (request.method === "HEAD") {
    headers.set("Content-Length", String(textEncoder.encode(body).byteLength));
    return new Response(null, { status: 200, headers });
  }
  return new Response(body, { status: 200, headers });
}

const textEncoder = new TextEncoder();

async function serveSnapshotObject(
  request: Request,
  env: Env,
  object: SnapshotObject,
): Promise<Response> {
  const headers = responseHeaders(object);
  if (request.method === "HEAD") {
    await headSnapshotObject(env.PRIVATE_FEEDS_BUCKET, object);
    if (requestIsNotModified(request, object)) {
      return new Response(null, { status: 304, headers });
    }
    return new Response(null, { status: 200, headers });
  }

  const stored = await getSnapshotObject(env.PRIVATE_FEEDS_BUCKET, object);
  if (requestIsNotModified(request, object)) {
    await stored.body.cancel();
    return new Response(null, { status: 304, headers });
  }
  return new Response(stored.body, { status: 200, headers });
}

export async function handleRequest(
  request: Request,
  env: Env,
): Promise<Response> {
  if (!(await isAuthorized(request, env))) {
    return unauthorizedResponse();
  }

  if (request.method !== "GET" && request.method !== "HEAD") {
    return methodNotAllowedResponse();
  }

  const url = new URL(request.url);
  const publicPath = url.pathname;
  if (!isPotentialPublicPath(publicPath) || publicPath.includes("%")) {
    return notFoundResponse();
  }

  try {
    if (publicPath === "/healthz") {
      return await healthResponse(request, env);
    }

    const active = await loadActiveSnapshot(env.PRIVATE_FEEDS_BUCKET);
    const object = resolveRoute(active.manifest, publicPath);
    if (!object) {
      return notFoundResponse();
    }
    return await serveSnapshotObject(request, env, object);
  } catch {
    return unavailableResponse();
  }
}

export default {
  fetch(request: Request, env: Env): Promise<Response> {
    return handleRequest(request, env);
  },
} satisfies ExportedHandler<Env>;
