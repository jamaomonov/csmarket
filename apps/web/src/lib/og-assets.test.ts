import { afterEach, describe, expect, it, vi } from "vitest";

import { ogFonts, ogSkinImage, resetOgFonts } from "./og-assets";

const STEAM = "https://community.fastly.steamstatic.com/economy/image/abc";

const CSS = `@font-face {
  font-family: 'IBM Plex Sans';
  font-weight: 500;
  src: url(https://fonts.gstatic.com/s/x/m.ttf) format('truetype');
}
@font-face {
  font-family: 'IBM Plex Sans';
  font-weight: 700;
  src: url(https://fonts.gstatic.com/s/x/b.ttf) format('truetype');
}`;

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
  it("loads both weights once per process", async () => {
    const fetchMock = vi.fn((url: string) =>
      Promise.resolve(url.endsWith(".ttf") ? new Response(new Uint8Array([0])) : new Response(CSS)),
    );
    vi.stubGlobal("fetch", fetchMock);
    const first = await ogFonts();
    expect(first.map((f) => f.weight)).toEqual([500, 700]);
    await ogFonts();
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("a failure gives the built-in font and is retried next time", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
    expect(await ogFonts()).toEqual([]);
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) =>
        Promise.resolve(
          url.endsWith(".ttf") ? new Response(new Uint8Array([0])) : new Response(CSS),
        ),
      ),
    );
    expect(await ogFonts()).toHaveLength(2);
  });

  it("a CSS answer without faces is a failure", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("")));
    expect(await ogFonts()).toEqual([]);
  });
});
