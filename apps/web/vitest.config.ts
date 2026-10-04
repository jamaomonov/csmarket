import path from "node:path";

import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
    },
  },
  // apps/web's tsconfig sets `jsx: "preserve"` (Next.js compiles JSX itself
  // via SWC); Vite/esbuild reads that as "classic" and needs `React` in
  // scope unless told to use the automatic runtime here.
  esbuild: { jsx: "automatic" },
  // Node by default; component tests opt into jsdom per file
  // (`// @vitest-environment jsdom`).
  test: {
    environment: "node",
    globals: true,
    include: ["src/**/*.test.{ts,tsx}"],
    setupFiles: ["./src/test/setup.ts"],
    // next-intl's ESM imports `next/navigation` without an extension, which Node's resolver
    // rejects; inlining lets Vite resolve it (tests can then use the real `getPathname`).
    server: { deps: { inline: ["next-intl"] } },
  },
});
