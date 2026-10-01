import { beforeEach, describe, expect, it, vi } from "vitest";

import { dynamic, GET } from "./route";

import { apiGet, apiGetOrNull } from "@/lib/server-api";

vi.mock("@/lib/server-api", () => ({ apiGet: vi.fn(), apiGetOrNull: vi.fn() }));
vi.mock("@/lib/api", () => ({ session: {} }));
const mockedApiGet = vi.mocked(apiGet);
const mockedApiGetOrNull = vi.mocked(apiGetOrNull);

const call = (file: string): Promise<Response> =>
  GET(new Request("https://csmarket.uz"), { params: Promise.resolve({ file }) });

describe("GET /skins-sitemap/<n>.xml", () => {
  beforeEach(() => {
    mockedApiGet.mockReset();
    mockedApiGetOrNull.mockReset();
  });

  it("lists that slice of item pages", async () => {
    mockedApiGet.mockResolvedValue({ items: ["ak-47-redline-field-tested"], total: 12_001 });
    const res = await call("2.xml");
    expect(res.headers.get("Content-Type")).toContain("xml");
    expect(await res.text()).toContain(
      "<loc>https://csmarket.uz/item/ak-47-redline-field-tested</loc>",
    );
    expect(mockedApiGet.mock.calls[0]?.[0]).toBe("/skins/seo/slugs?offset=10000&limit=5000");
    expect(mockedApiGet.mock.calls[0]?.[1]).toMatchObject({ revalidate: 3600 });
  });

  it("404s a name that is not a file", async () => {
    expect((await call("x.xml")).status).toBe(404);
    expect((await call("-1.xml")).status).toBe(404);
    expect((await call("1")).status).toBe(404);
  });

  it("404s a slice past the end", async () => {
    mockedApiGet.mockResolvedValue({ items: [], total: 10 });
    expect((await call("3.xml")).status).toBe(404);
  });

  it("lists the home page and the category and weapon landing pages", async () => {
    mockedApiGetOrNull.mockResolvedValue({
      categories: [{ value: "knives", count: 3505 }],
      weapons: [{ value: "AK-47", count: 594 }],
      exteriors: [],
      rarities: [],
    });
    const body = await (await call("landings.xml")).text();
    expect(body).toContain("<loc>https://csmarket.uz/</loc>");
    expect(body).toContain("<loc>https://csmarket.uz/category/knives</loc>");
    expect(body).toContain("<loc>https://csmarket.uz/en/weapon/ak-47</loc>");
  });

  it("404s the landings only when the API has no facets", async () => {
    mockedApiGetOrNull.mockResolvedValue(null);
    expect((await call("landings.xml")).status).toBe(404);
  });

  it("is rendered per request, so `next build` never needs the API", () => {
    expect(dynamic).toBe("force-dynamic");
  });
});
