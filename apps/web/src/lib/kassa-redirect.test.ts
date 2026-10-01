// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";

import { markOpened, searchWithoutGo, shouldAutoOpen } from "./kassa-redirect";

afterEach(() => {
  vi.restoreAllMocks();
  window.sessionStorage.clear();
});

describe("shouldAutoOpen", () => {
  it("is true for ?go=1 until the top-up is marked opened in this tab", () => {
    expect(shouldAutoOpen("T100", "?go=1")).toBe(true);
    expect(shouldAutoOpen("T100", "?go=1")).toBe(true);
    markOpened("T100");
    expect(shouldAutoOpen("T100", "?go=1")).toBe(false);
    expect(window.sessionStorage.getItem("csmarket.web.kassa_opened.T100")).toBe("1");
  });

  it("is per top-up", () => {
    markOpened("T101");
    expect(shouldAutoOpen("T102", "?go=1")).toBe(true);
  });

  it("needs the exact flag", () => {
    for (const search of ["", "?go=0", "?go=", "?mock=1", "go=1x"]) {
      expect(shouldAutoOpen("T103", search)).toBe(false);
    }
    expect(shouldAutoOpen("T103", "?mock=1&go=1")).toBe(true);
    expect(shouldAutoOpen("T103", "go=1")).toBe(true);
  });

  it("opens once even when the browser refuses sessionStorage", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });
    expect(shouldAutoOpen("T104", "?go=1")).toBe(true);
    expect(() => {
      markOpened("T104");
    }).not.toThrow();
    // Remembered for this page load at least.
    expect(shouldAutoOpen("T104", "?go=1")).toBe(false);
  });

  it("survives sessionStorage itself being unreachable", () => {
    vi.spyOn(window, "sessionStorage", "get").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });
    expect(shouldAutoOpen("T105", "?go=1")).toBe(true);
    markOpened("T105");
    expect(shouldAutoOpen("T105", "?go=1")).toBe(false);
  });
});

describe("searchWithoutGo", () => {
  it("drops the flag and keeps the rest", () => {
    expect(searchWithoutGo("?go=1")).toBe("");
    expect(searchWithoutGo("?mock=1&go=1")).toBe("?mock=1");
    expect(searchWithoutGo("")).toBe("");
  });
});
