import { describe, expect, it } from "vitest";

import { GET } from "./route";

describe("robots.txt", () => {
  it("keeps the pre-launch page out of every index", async () => {
    const body = await GET().text();
    expect(body).toContain("User-Agent: *");
    expect(body).toContain("Disallow: /");
    expect(body).not.toContain("Sitemap:");
  });
});
