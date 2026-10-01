import { beforeEach, describe, expect, it, vi } from "vitest";

import { dynamic, GET } from "./route";

import { apiGet } from "@/lib/server-api";

vi.mock("@/lib/server-api", () => ({ apiGet: vi.fn(), apiGetOrNull: vi.fn() }));
// The browser session client pulled in by `@/lib/skins` is not needed here.
vi.mock("@/lib/api", () => ({ session: {} }));
const mockedApiGet = vi.mocked(apiGet);

describe("GET /sitemap.xml", () => {
  beforeEach(() => {
    mockedApiGet.mockReset();
  });

  it("indexes one file per 5000 items and the landing pages", async () => {
    mockedApiGet.mockResolvedValue({ items: ["a"], total: 12_001 });
    const res = await GET();
    expect(res.headers.get("Content-Type")).toContain("xml");
    const body = await res.text();
    expect(body).toContain("<sitemapindex");
    expect(body).toContain("https://csmarket.uz/skins-sitemap/0.xml");
    expect(body).toContain("https://csmarket.uz/skins-sitemap/2.xml");
    expect(body).not.toContain("https://csmarket.uz/skins-sitemap/3.xml");
    expect(body).toContain("https://csmarket.uz/skins-sitemap/landings.xml");
  });

  it("still lists the landings for an empty catalogue", async () => {
    mockedApiGet.mockResolvedValue({ items: [], total: 0 });
    const body = await (await GET()).text();
    expect(body).not.toContain("/skins-sitemap/0.xml");
    expect(body).toContain("/skins-sitemap/landings.xml");
  });

  it("is rendered per request, so `next build` never needs the API", () => {
    expect(dynamic).toBe("force-dynamic");
  });
});
