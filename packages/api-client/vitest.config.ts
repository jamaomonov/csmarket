import { defineConfig } from "vitest/config";

// The session client reads `localStorage` and `navigator`; jsdom provides both.
export default defineConfig({ test: { environment: "jsdom", globals: true } });
