import { afterEach, describe, expect, it, vi } from "vitest";

import { copyLater, copyText } from "./clipboard";

function setClipboard(value: unknown) {
  Object.defineProperty(navigator, "clipboard", { value, configurable: true });
}

describe("clipboard", () => {
  afterEach(() => {
    setClipboard(undefined);
    vi.unstubAllGlobals();
  });

  it("copyText uses the Clipboard API", async () => {
    const writeText = vi.fn(() => Promise.resolve());
    setClipboard({ writeText });
    expect(await copyText("147400")).toBe(true);
    expect(writeText).toHaveBeenCalledWith("147400");
  });

  it("copyText falls back to execCommand when the API refuses", async () => {
    setClipboard({ writeText: vi.fn(() => Promise.reject(new Error("NotAllowed"))) });
    const exec = vi.fn(() => true);
    Object.assign(document, { execCommand: exec });
    expect(await copyText("147400")).toBe(true);
    expect(exec).toHaveBeenCalledWith("copy");
  });

  it("copyLater hands a ClipboardItem to the clipboard inside the tap", async () => {
    const write = vi.fn(() => Promise.resolve());
    setClipboard({ write, writeText: vi.fn() });
    class FakeItem {
      constructor(public items: Record<string, Promise<Blob>>) {}
    }
    vi.stubGlobal("ClipboardItem", FakeItem);
    expect(await copyLater(Promise.resolve("9860123456789015"))).toBe(true);
    expect(write).toHaveBeenCalledTimes(1);
  });

  it("copyLater writes the text when it arrives without ClipboardItem", async () => {
    const writeText = vi.fn(() => Promise.resolve());
    setClipboard({ writeText });
    expect(await copyLater(Promise.resolve("9860123456789015"))).toBe(true);
    expect(writeText).toHaveBeenCalledWith("9860123456789015");
  });

  it("copyLater says false when nothing works", async () => {
    setClipboard(undefined);
    Object.assign(document, { execCommand: vi.fn(() => false) });
    expect(await copyLater(Promise.resolve("1"))).toBe(false);
  });
});
