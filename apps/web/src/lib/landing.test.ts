import { afterEach, describe, expect, it, vi } from "vitest";

const cached = vi.hoisted(() => [] as (() => Promise<unknown>)[]);
vi.mock("next/cache", () => ({
  // Pass-through that keeps the function handed to the cache: what it throws is never stored.
  unstable_cache: (fn: () => Promise<unknown>) => {
    cached.push(fn);
    return fn;
  },
}));

import {
  getCategoryTiles,
  getHero,
  getLandingData,
  getPopular,
  getStats,
  HERO_QUERIES,
  loadLanding,
  POPULAR_SIZE,
  POPULAR_TABS,
  WALL_SIZE,
  wallItems,
} from "./landing";

const item = (slug: string, category = "rifles", price = "1000") => ({
  slug,
  name: slug,
  phase: null,
  category,
  weapon: null,
  skin: null,
  exterior: null,
  stattrak: false,
  souvenir: false,
  rarity: null,
  rarity_color: "#eb4b4b",
  image_url: null,
  price_usd: "1",
  price_uzs: price,
  steam_price_usd: null,
  discount_percent: null,
  count: 1,
  min_float: null,
  max_float: null,
});
const ok = (body: unknown) =>
  new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
const page = (items: unknown[]) => ok({ items, next_cursor: null });
const params = (url: string) => new URL(url).searchParams;

describe("landing data", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("the hero takes each curated query's first hit, in order", async () => {
    const f = vi.fn((url: string) => Promise.resolve(page([item(params(url).get("q") ?? "")])));
    vi.stubGlobal("fetch", f);
    const hero = await getHero();
    expect(hero.map((h) => h.slug)).toEqual(HERO_QUERIES.map((q) => q.q));
    expect(params(String(f.mock.calls[0]?.[0])).get("limit")).toBe("1");
  });

  it("skips what is out of stock and tops up with the dearest knives below three", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        const p = params(url);
        if (p.get("sort") === "-price") return Promise.resolve(page([item("k1"), item("k2")]));
        return Promise.resolve(page(p.get("q") === "Karambit Fade" ? [item("karambit")] : []));
      }),
    );
    expect((await getHero()).map((h) => h.slug)).toEqual(["karambit", "k1", "k2"]);
  });

  it("an API outage is an empty block, never a throw", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("", { status: 503 })));
    await expect(getHero()).resolves.toEqual([]);
    await expect(getPopular("popular")).resolves.toEqual([]);
    await expect(getStats()).resolves.toEqual({ inStock: 0, fromUzs: null });
    const tiles = await getCategoryTiles();
    expect(tiles.every((t) => t.item === null && t.fromUzs === null)).toBe(true);
  });

  it("«Популярное» mixes weapon skins, knives and gloves — never cases", async () => {
    const f = vi.fn((url: string) => {
      const c = params(url).get("category") ?? "";
      return Promise.resolve(page([1, 2, 3, 4].map((n) => item(`${c}-${String(n)}`, c))));
    });
    vi.stubGlobal("fetch", f);
    const cards = await getPopular("popular");
    expect(cards).toHaveLength(POPULAR_SIZE);
    expect(cards.slice(0, 3).map((c) => c.category)).toEqual(["rifles", "knives", "gloves"]);
    const asked = f.mock.calls.map((c) => params(c[0]).get("category"));
    expect(asked).not.toContain("cases");
  });

  it("«До 100 000 сум» asks for weapon skins under the cap", async () => {
    const f = vi.fn(() => Promise.resolve(page([])));
    vi.stubGlobal("fetch", f);
    await getPopular("cheap");
    for (const call of f.mock.calls as unknown as [string][]) {
      expect(params(call[0]).get("max_uzs")).toBe("100000");
    }
  });

  it("stats add up every category and take the cheapest price", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) =>
        Promise.resolve(
          url.includes("/facets")
            ? ok({
                categories: [
                  { value: "rifles", count: 30 },
                  { value: "knives", count: 5 },
                ],
                weapons: [],
                exteriors: [],
                rarities: [],
              })
            : page([item("cheap", "cases", "1200")]),
        ),
      ),
    );
    expect(await getStats()).toEqual({ inStock: 35, fromUzs: "1200" });
  });

  it("loads every block in one pass, one list per popular tab", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("", { status: 503 })));
    const data = await loadLanding();
    expect(Object.keys(data.popular)).toEqual(POPULAR_TABS);
    expect(data.hero).toEqual([]);
    expect(data.stats).toEqual({ inStock: 0, fromUzs: null });
  });

  it("an outage is served but never cached", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("", { status: 503 })));
    await expect(cached[0]?.()).rejects.toThrow();
    const data = await getLandingData();
    expect(data.stats.inStock).toBe(0);
    expect(data.tiles.every((t) => t.item === null)).toBe(true);
  });

  it("the hero wall leads with the showcase, interleaves the tabs, skips repeats and bare items", () => {
    const pic = (slug: string) => ({ ...item(slug), image_url: "https://x/img" });
    const wall = wallItems({
      hero: [pic("h1"), pic("k1")],
      popular: {
        knives: [pic("k1"), pic("k2")],
        gloves: [pic("g1"), { ...pic("g2"), price_uzs: null }],
        popular: [pic("p1"), item("p2")],
        cheap: [pic("c1")],
      },
    });
    expect(wall.map((w) => w.slug)).toEqual(["h1", "k1", "g1", "p1", "k2"]);
  });

  it("the hero wall stops at its size", () => {
    const many = Array.from({ length: 40 }, (_, i) => ({
      ...item(`s${String(i)}`),
      image_url: "u",
    }));
    const wall = wallItems({
      hero: [],
      popular: { knives: many, gloves: [], popular: [], cheap: [] },
    });
    expect(wall).toHaveLength(WALL_SIZE);
  });
});
