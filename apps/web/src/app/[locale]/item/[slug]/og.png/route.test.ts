import { beforeEach, describe, expect, it, vi } from "vitest";

const { apiGetOrNull } = vi.hoisted(() => ({ apiGetOrNull: vi.fn<() => Promise<unknown>>() }));
vi.mock("@/lib/server-api", () => ({ apiGetOrNull }));
vi.mock("next-intl/server", () => ({
  getTranslations: () => Promise.resolve((k: string) => k),
}));
// No network in tests: the built-in font, no picture (the fallback mark).
vi.mock("@/lib/og-assets", () => ({
  ogFonts: () => Promise.resolve([]),
  ogSkinImage: () => Promise.resolve(null),
}));

import { dynamic, GET } from "./route";

const call = (locale: string, slug: string) =>
  GET(new Request("http://x/"), { params: Promise.resolve({ locale, slug }) });

beforeEach(() => apiGetOrNull.mockReset());

describe("item og.png", () => {
  it("draws a cacheable 1200×630 PNG from the day-cached item", async () => {
    apiGetOrNull.mockResolvedValueOnce({
      name: "AK-47 | Redline (Field-Tested)",
      phase: null,
      category: "rifles",
      weapon: "AK-47",
      skin: "Redline",
      exterior: "FT",
      stattrak: false,
      souvenir: false,
      rarity: "Classified",
      rarity_color: "#d32ce6",
      image_url: null,
    });
    const res = await call("ru", "ak-47-redline-ft");
    expect(res.status).toBe(200);
    expect(res.headers.get("content-type")).toBe("image/png");
    expect(res.headers.get("cache-control")).toContain("s-maxage=86400");
    const png = new Uint8Array(await res.arrayBuffer());
    expect([...png.slice(1, 4)].map((c) => String.fromCharCode(c)).join("")).toBe("PNG");
    expect(apiGetOrNull).toHaveBeenCalledWith("/skins/ak-47-redline-ft", { revalidate: 86400 });
  });

  it("an unknown item or locale is a 404", async () => {
    apiGetOrNull.mockResolvedValueOnce(null);
    expect((await call("ru", "nope")).status).toBe(404);
    expect((await call("de", "x")).status).toBe(404);
  });

  it("an API outage sends the generic card, uncached", async () => {
    apiGetOrNull.mockRejectedValueOnce(new Error("ECONNREFUSED"));
    const res = await call("uz", "x");
    expect(res.status).toBe(302);
    expect(res.headers.get("location")).toBe("/og/uz.jpg");
    expect(res.headers.get("cache-control")).toBe("no-store");
  });

  it("is rendered per request, so the build never needs the API", () => {
    expect(dynamic).toBe("force-dynamic");
  });
});
