import { afterEach, describe, expect, it, vi } from "vitest";

import { displayPrice, getSkinDetail, getSkinFacets, getSkinsPage } from "./skins";

const res = (status: number, body: unknown = {}) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

describe("skins data", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("a 404 is null", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(res(404)));
    await expect(getSkinDetail("nope")).resolves.toBeNull();
    await expect(getSkinFacets("nope")).resolves.toBeNull();
  });

  it("an outage throws — never a 404", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(res(503)));
    await expect(getSkinDetail("ak")).rejects.toThrow();
    await expect(getSkinFacets()).rejects.toThrow();
    await expect(getSkinsPage({ sort: "-price" })).rejects.toThrow();
  });

  it("asks the API with the query's params", async () => {
    const f = vi.fn().mockResolvedValue(res(200, { items: [], next_cursor: null }));
    vi.stubGlobal("fetch", f);
    await getSkinsPage({ sort: "price", category: "knives", minUzs: 1000 });
    const url = String(f.mock.calls[0]?.[0]);
    expect(url).toContain("/api/v1/skins/catalog?");
    expect(url).toContain("category=knives");
    expect(url).toContain("sort=price");
    expect(url).toContain("min_uzs=1000");
  });

  it("sends no Accept-Language and caches under the skins tag", async () => {
    const f = vi.fn().mockResolvedValue(res(200, { items: [], next_cursor: null }));
    vi.stubGlobal("fetch", f);
    await getSkinsPage({ sort: "-price" });
    const init = f.mock.calls[0]?.[1] as { headers?: Record<string, string>; next?: unknown };
    expect(init.headers?.["Accept-Language"]).toBeUndefined();
    expect(init.next).toEqual({ revalidate: 60, tags: ["skins"] });
  });

  it("asks facets for a category only when one is given", async () => {
    const f = vi.fn().mockImplementation(() => Promise.resolve(res(200, {})));
    vi.stubGlobal("fetch", f);
    await getSkinFacets();
    await getSkinFacets("knives");
    expect(String(f.mock.calls[0]?.[0])).toMatch(/\/skins\/facets$/);
    expect(String(f.mock.calls[1]?.[0])).toMatch(/\/skins\/facets\?category=knives$/);
  });
});

describe("displayPrice", () => {
  it("prefers soʻm, falls back to USD, else null", () => {
    expect(displayPrice("uz", "1250000", "99.00")?.replace(/\s/g, " ")).toBe("1 250 000 soʻm");
    expect(displayPrice("en", null, "99.00")).toBe("$99.00");
    expect(displayPrice("ru", null, null)).toBeNull();
  });
});
