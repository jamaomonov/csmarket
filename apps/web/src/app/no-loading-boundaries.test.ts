import { readdirSync, statSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    return statSync(p).isDirectory() ? walk(p) : [p];
  });
}

describe("real 404s", () => {
  it("no loading.tsx anywhere under app/ — a Suspense boundary above a page turns notFound() into a 200", () => {
    const loading = walk(join(__dirname)).filter((p) => /[/\\]loading\.tsx$/.test(p));
    expect(loading).toEqual([]);
  });
});
