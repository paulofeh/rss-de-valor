import type { Env } from "./types";

const textEncoder = new TextEncoder();
const utf8Decoder = new TextDecoder("utf-8", { fatal: true });
const MAX_CREDENTIAL_LENGTH = 4096;
const MAX_USERNAME_BYTES = 128;
const MIN_PASSWORD_BYTES = 24;
const MAX_PASSWORD_BYTES = 1024;
const UNAUTHORIZED_BODY = "Authentication required.\n";

interface ParsedCredentials {
  username: string;
  password: string;
}

interface TimingSafeSubtleCrypto extends SubtleCrypto {
  timingSafeEqual(
    left: ArrayBuffer | ArrayBufferView,
    right: ArrayBuffer | ArrayBufferView,
  ): boolean;
}

function decodeBasicCredentials(
  authorization: string | null,
): ParsedCredentials | null {
  if (!authorization) {
    return null;
  }

  const match = /^Basic ([A-Za-z0-9+/]+={0,2})$/i.exec(authorization);
  if (!match) {
    return null;
  }

  const encoded = match[1];
  if (
    !encoded ||
    encoded.length > MAX_CREDENTIAL_LENGTH ||
    encoded.length % 4 !== 0
  ) {
    return null;
  }

  try {
    const binary = atob(encoded);
    if (
      btoa(binary).replace(/=+$/u, "") !== encoded.replace(/=+$/u, "")
    ) {
      return null;
    }

    const bytes = Uint8Array.from(binary, (character) =>
      character.charCodeAt(0),
    );
    const decoded = utf8Decoder.decode(bytes);
    const separator = decoded.indexOf(":");
    if (separator < 0) {
      return null;
    }

    return {
      username: decoded.slice(0, separator),
      password: decoded.slice(separator + 1),
    };
  } catch {
    return null;
  }
}

async function sha256(value: string): Promise<ArrayBuffer> {
  return crypto.subtle.digest("SHA-256", textEncoder.encode(value));
}

function configuredUsernameIsValid(value: string | undefined): boolean {
  if (!value || value !== value.trim() || value.includes(":")) {
    return false;
  }
  const bytes = textEncoder.encode(value);
  return (
    bytes.byteLength <= MAX_USERNAME_BYTES &&
    ![...bytes].some((byte) => byte < 0x20 || byte === 0x7f)
  );
}

function configuredPasswordIsValid(value: string | undefined): boolean {
  if (!value) {
    return false;
  }
  const length = textEncoder.encode(value).byteLength;
  return length >= MIN_PASSWORD_BYTES && length <= MAX_PASSWORD_BYTES;
}

export async function constantTimeStringEqual(
  candidate: string,
  expected: string,
): Promise<boolean> {
  const [candidateDigest, expectedDigest] = await Promise.all([
    sha256(candidate),
    sha256(expected),
  ]);
  const subtle = crypto.subtle as TimingSafeSubtleCrypto;
  return subtle.timingSafeEqual(candidateDigest, expectedDigest);
}

export async function isAuthorized(
  request: Request,
  env: Pick<
    Env,
    | "BASIC_AUTH_USERNAME"
    | "BASIC_AUTH_PASSWORD_CURRENT"
    | "BASIC_AUTH_USERNAME_NEXT"
    | "BASIC_AUTH_PASSWORD_NEXT"
  >,
): Promise<boolean> {
  const credentials = decodeBasicCredentials(
    request.headers.get("Authorization"),
  );
  const candidateUsername = credentials?.username ?? "\u0000";
  const candidatePassword = credentials?.password ?? "\u0000";
  const nextUsername =
    env.BASIC_AUTH_USERNAME_NEXT === undefined
      ? (env.BASIC_AUTH_USERNAME ?? "")
      : env.BASIC_AUTH_USERNAME_NEXT;
  const nextPassword = env.BASIC_AUTH_PASSWORD_NEXT ?? "\u0000";

  const [
    currentUsernameMatches,
    currentPasswordMatches,
    nextUsernameMatches,
    nextPasswordMatches,
  ] = await Promise.all([
      constantTimeStringEqual(candidateUsername, env.BASIC_AUTH_USERNAME ?? ""),
      constantTimeStringEqual(
        candidatePassword,
        env.BASIC_AUTH_PASSWORD_CURRENT ?? "",
      ),
      constantTimeStringEqual(candidateUsername, nextUsername),
      constantTimeStringEqual(candidatePassword, nextPassword),
    ]);

  const currentCredentialsConfigured =
    configuredUsernameIsValid(env.BASIC_AUTH_USERNAME) &&
    configuredPasswordIsValid(env.BASIC_AUTH_PASSWORD_CURRENT);
  const nextCredentialsConfigured =
    configuredUsernameIsValid(nextUsername) &&
    configuredPasswordIsValid(env.BASIC_AUTH_PASSWORD_NEXT);

  return Boolean(
    credentials &&
      currentCredentialsConfigured &&
      ((currentUsernameMatches && currentPasswordMatches) ||
        (nextCredentialsConfigured &&
          nextUsernameMatches &&
          nextPasswordMatches)),
  );
}

export function unauthorizedResponse(): Response {
  return new Response(UNAUTHORIZED_BODY, {
    status: 401,
    headers: {
      "Cache-Control": "no-store",
      "CDN-Cache-Control": "no-store",
      "Cloudflare-CDN-Cache-Control": "no-store",
      "Content-Type": "text/plain; charset=utf-8",
      "Vary": "Authorization",
      "WWW-Authenticate": 'Basic realm="Private feeds", charset="UTF-8"',
      "X-Content-Type-Options": "nosniff",
    },
  });
}
