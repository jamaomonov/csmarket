import { existsSync } from "node:fs";
import { join } from "node:path";

import { expect, test } from "vitest";

import manifest from "./manifest";

test("every icon the manifest names ships in public/", () => {
  const icons = manifest().icons ?? [];
  expect(icons.length).toBeGreaterThan(0);
  for (const icon of icons) {
    expect(existsSync(join(__dirname, "../../public", icon.src))).toBe(true);
  }
  expect(existsSync(join(__dirname, "../../public/favicon.ico"))).toBe(true);
});
