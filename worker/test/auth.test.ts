import { describe, expect, it } from "vitest";
import {
  constantTimeStringEqual,
  isAuthorized,
  unauthorizedResponse,
} from "../src/auth";

const authEnv = {
  BASIC_AUTH_USERNAME: "feed-reader",
  BASIC_AUTH_PASSWORD_CURRENT: "current-secret-with-enough-length",
  BASIC_AUTH_PASSWORD_NEXT: "next-secret-with-enough-length",
};

function authorization(username: string, password: string): string {
  return `Basic ${btoa(`${username}:${password}`)}`;
}

function request(header?: string): Request {
  return new Request("https://example.com/feeds/pilot_feed.xml", {
    headers: header ? { Authorization: header } : undefined,
  });
}

describe("Basic authentication", () => {
  it("compares equal and unequal strings with fixed-length digests", async () => {
    await expect(constantTimeStringEqual("same", "same")).resolves.toBe(true);
    await expect(constantTimeStringEqual("same", "different")).resolves.toBe(
      false,
    );
  });

  it("accepts the current password", async () => {
    await expect(
      isAuthorized(
        request(
          authorization("feed-reader", "current-secret-with-enough-length"),
        ),
        authEnv,
      ),
    ).resolves.toBe(true);
  });

  it("accepts the transition password", async () => {
    await expect(
      isAuthorized(
        request(authorization("feed-reader", "next-secret-with-enough-length")),
        authEnv,
      ),
    ).resolves.toBe(true);
  });

  it("accepts a transition credential pair without accepting crossed pairs", async () => {
    const transitionEnv = {
      ...authEnv,
      BASIC_AUTH_USERNAME_NEXT: "next-feed-reader",
    };

    await expect(
      isAuthorized(
        request(
          authorization(
            "next-feed-reader",
            "next-secret-with-enough-length",
          ),
        ),
        transitionEnv,
      ),
    ).resolves.toBe(true);
    await expect(
      isAuthorized(
        request(
          authorization("feed-reader", "next-secret-with-enough-length"),
        ),
        transitionEnv,
      ),
    ).resolves.toBe(false);
    await expect(
      isAuthorized(
        request(
          authorization(
            "next-feed-reader",
            "current-secret-with-enough-length",
          ),
        ),
        transitionEnv,
      ),
    ).resolves.toBe(false);
  });

  it("rejects missing, malformed and invalid credentials", async () => {
    const candidates = [
      request(),
      request("Bearer token"),
      request("Basic !!!"),
      request("Basic dXNlcg=="),
      request(
        authorization("wrong-user", "current-secret-with-enough-length"),
      ),
      request(authorization("feed-reader", "wrong-password")),
    ];

    for (const candidate of candidates) {
      await expect(isAuthorized(candidate, authEnv)).resolves.toBe(false);
    }
  });

  it("fails closed when required secrets are absent", async () => {
    await expect(
      isAuthorized(request(authorization("", "")), {
        BASIC_AUTH_USERNAME: "",
        BASIC_AUTH_PASSWORD_CURRENT: "",
      }),
    ).resolves.toBe(false);
  });

  it("fails closed when configured credentials are weak or ambiguous", async () => {
    await expect(
      isAuthorized(
        request(authorization("feed-reader", "too-short")),
        {
          BASIC_AUTH_USERNAME: "feed-reader",
          BASIC_AUTH_PASSWORD_CURRENT: "too-short",
        },
      ),
    ).resolves.toBe(false);
    await expect(
      isAuthorized(
        request(
          authorization(
            "feed:reader",
            "current-secret-with-enough-length",
          ),
        ),
        {
          BASIC_AUTH_USERNAME: "feed:reader",
          BASIC_AUTH_PASSWORD_CURRENT: "current-secret-with-enough-length",
        },
      ),
    ).resolves.toBe(false);
    await expect(
      isAuthorized(
        request(
          authorization(
            "next-feed-reader",
            "next-secret-with-enough-length",
          ),
        ),
        {
          ...authEnv,
          BASIC_AUTH_USERNAME_NEXT: "next:feed-reader",
        },
      ),
    ).resolves.toBe(false);
  });

  it("uses one generic challenge for every authentication failure", async () => {
    const first = unauthorizedResponse();
    const second = unauthorizedResponse();

    expect(first.status).toBe(401);
    expect(first.headers.get("WWW-Authenticate")).toBe(
      'Basic realm="Private feeds", charset="UTF-8"',
    );
    expect(first.headers.get("Cache-Control")).toBe("no-store");
    expect(await first.text()).toBe(await second.text());
  });
});
