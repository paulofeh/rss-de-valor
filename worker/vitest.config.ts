import { cloudflareTest } from "@cloudflare/vitest-pool-workers";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [
    cloudflareTest({
      wrangler: {
        configPath: "./wrangler.jsonc",
      },
      miniflare: {
        bindings: {
          BASIC_AUTH_USERNAME: "feed-reader",
          BASIC_AUTH_PASSWORD_CURRENT: "current-secret-with-enough-length",
          BASIC_AUTH_PASSWORD_NEXT: "next-secret-with-enough-length",
        },
      },
    }),
  ],
  test: {
    include: ["test/**/*.test.ts"],
  },
});
