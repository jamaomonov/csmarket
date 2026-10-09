import { beforeEach, describe, expect, it, vi } from "vitest";

const { getSkinsPage } = vi.hoisted(() => ({ getSkinsPage: vi.fn() }));
vi.mock("@/lib/skins", () => ({ getSkinsPage }));

import { SIMILAR, similarSkins } from "./skin-similar";

const it_ = (slug: string, skin: string | null, weapon: string | null = "AK-47") => ({
  slug,
  skin,
  weapon,
});

describe("similarSkins", () => {
  beforeEach(() => {
    getSkinsPage.mockReset();
  });

  it("other skins of the weapon, popular first, without the item's own family", async () => {
    getSkinsPage.mockResolvedValue({
      items: [
        it_("ak-redline-ft", "Redline"),
        it_("ak-redline-mw", "Redline"),
        it_("ak-slate", "Slate"),
      ],
      next_cursor: null,
    });
    const out = await similarSkins({
      slug: "ak-redline-ft",
      skin: "Redline",
      weapon: "AK-47",
      category: "rifles",
    });
    expect(getSkinsPage).toHaveBeenCalledWith({ sort: "popular", weapon: "AK-47" });
    expect(out.map((i) => i.slug)).toEqual(["ak-slate"]);
  });

  it("an item without a weapon looks in its section; an unknown section gets nothing", async () => {
    getSkinsPage.mockResolvedValue({
      items: [it_("a", null, null), it_("b", null, null)],
      next_cursor: null,
    });
    const out = await similarSkins({ slug: "a", skin: null, weapon: null, category: "cases" });
    expect(getSkinsPage).toHaveBeenCalledWith({ sort: "popular", category: "cases" });
    expect(out.map((i) => i.slug)).toEqual(["b"]);
    expect(
      await similarSkins({ slug: "x", skin: null, weapon: null, category: "stickers" }),
    ).toEqual([]);
  });

  it("one card per skin: other wears of a neighbour do not repeat", async () => {
    getSkinsPage.mockResolvedValue({
      items: [it_("asi-ft", "Asiimov"), it_("asi-mw", "Asiimov"), it_("paw", "PAW")],
      next_cursor: null,
    });
    const out = await similarSkins({ slug: "z", skin: "Z", weapon: "AWP", category: "rifles" });
    expect(out.map((i) => i.slug)).toEqual(["asi-ft", "paw"]);
  });

  it("caps the list and survives an API failure", async () => {
    getSkinsPage.mockResolvedValue({
      items: Array.from({ length: 30 }, (_, i) => it_(`s${String(i)}`, `S${String(i)}`)),
      next_cursor: null,
    });
    expect(
      await similarSkins({ slug: "z", skin: "Z", weapon: "AK-47", category: "rifles" }),
    ).toHaveLength(SIMILAR);
    getSkinsPage.mockRejectedValue(new Error("API 503"));
    expect(
      await similarSkins({ slug: "z", skin: "Z", weapon: "AK-47", category: "rifles" }),
    ).toEqual([]);
  });
});
