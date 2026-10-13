import { describe, expect, it, vi } from "vitest";

const state = vi.hoisted(() => ({ header: null as string | null }));
vi.mock("next/headers", () => ({
  headers: () =>
    Promise.resolve(new Headers(state.header ? { "x-csmarket-md": state.header } : {})),
}));
vi.mock("@/lib/agent-md-pages", () => ({
  homeMd: () => Promise.resolve("# Home\n"),
  marketMd: () => Promise.resolve("# Market\n"),
  categoryMd: (_l: string, c: string) => Promise.resolve(c === "knives" ? "# Knives\n" : null),
  weaponMd: () => Promise.resolve(null),
  itemMd: () => Promise.resolve("# Item\n"),
}));

import { GET } from "./route";

const get = (path: string[]) =>
  GET(new Request("https://csmarket.uz/md"), { params: Promise.resolve({ path }) });

describe("/md/…", () => {
  it("is a 404 when opened directly", async () => {
    state.header = null;
    expect((await get(["ru", "market"])).status).toBe(404);
  });

  it("answers Markdown behind the middleware's mark", async () => {
    state.header = "1";
    const res = await get(["uz", "category", "knives"]);
    expect(res.status).toBe(200);
    expect(res.headers.get("content-type")).toBe("text/markdown; charset=utf-8");
    expect(res.headers.get("x-robots-tag")).toBe("noindex");
    expect(await res.text()).toBe("# Knives\n");
    expect(await (await get(["ru"])).text()).toBe("# Home\n");
  });

  it("is a 404 for what the catalogue does not have", async () => {
    state.header = "1";
    expect((await get(["ru", "category", "nope"])).status).toBe(404);
    expect((await get(["ru", "weapon", "nope"])).status).toBe(404);
    expect((await get(["ru", "account"])).status).toBe(404);
  });
});
