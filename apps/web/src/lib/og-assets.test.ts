import { afterEach, describe, expect, it, vi } from "vitest";

import { ogFonts, ogSkinImage, resetOgFonts } from "./og-assets";

const STEAM = "https://community.fastly.steamstatic.com/economy/image/abc";

afterEach(() => {
  vi.unstubAllGlobals();
  resetOgFonts();
});

describe("ogSkinImage", () => {
  it("fetches the 512×384 size and inlines it", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        new Response(new Uint8Array([1, 2, 3]), { headers: { "content-type": "image/png" } }),
      );
    vi.stubGlobal("fetch", fetchMock);
    expect(await ogSkinImage(STEAM)).toBe("data:image/png;base64,AQID");
    expect(fetchMock.mock.calls[0]?.[0]).toBe(`${STEAM}/512fx384f`);
  });

  it("no URL, an error status, a non-image or a network failure is null", async () => {
    expect(await ogSkinImage(null)).toBeNull();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("x", { status: 404 })));
    expect(await ogSkinImage(STEAM)).toBeNull();
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(new Response("<html>", { headers: { "content-type": "text/html" } })),
    );
    expect(await ogSkinImage(STEAM)).toBeNull();
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("timeout")));
    expect(await ogSkinImage(STEAM)).toBeNull();
  });
});

describe("ogFonts", () => {
  it("reads both weights from the repo, without the network", async () => {
    const fetchMock = vi.fn().mockRejectedValue(new Error("offline"));
    vi.stubGlobal("fetch", fetchMock);
    const fonts = await ogFonts();
    expect(fonts.map((f) => f.weight)).toEqual([500, 700]);
    expect(fonts.every((f) => f.data.byteLength > 100_000)).toBe(true);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("is read once per process", async () => {
    const first = await ogFonts();
    expect(await ogFonts()).toBe(first);
  });
});
