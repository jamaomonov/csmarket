// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest";

import { isGood, LIVE_SKEW_MS, shouldOpenLive, takeStripTurn, type PendingDeal } from "./reviews";

const VISIT = Date.parse("2026-10-23T10:00:00Z");
const deal = (number: string, doneAt: number): PendingDeal => ({
  kind: "market",
  number,
  title: "AK-47 | Redline (Field-Tested)",
  image_url: null,
  items: 1,
  done_at: new Date(doneAt).toISOString(),
});
const check = (initialNumber: string | null, opened: string[] = []) => ({
  initialNumber,
  opened: new Set(opened),
  visitStartMs: VISIT,
});

describe("reviews rules", () => {
  it("good is 4–5 stars", () => {
    expect([1, 2, 3, 4, 5].map(isGood)).toEqual([false, false, false, true, true]);
  });

  it("opens the modal only for a deal that succeeded during this visit, once", () => {
    expect(shouldOpenLive(deal("A", VISIT + 1000), check(null))).toBe(true);
    expect(shouldOpenLive(deal("A", VISIT - LIVE_SKEW_MS), check(null))).toBe(true);
    expect(shouldOpenLive(deal("A", VISIT - LIVE_SKEW_MS - 1), check(null))).toBe(false);
    expect(shouldOpenLive(deal("A", VISIT + 1000), check("A"))).toBe(false);
    expect(shouldOpenLive(deal("A", VISIT + 1000), check(null, ["A"]))).toBe(false);
    expect(shouldOpenLive(null, check(null))).toBe(false);
  });
});

describe("takeStripTurn", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    vi.restoreAllMocks();
  });

  it("is true once per tab session", () => {
    expect(takeStripTurn()).toBe(true);
    expect(takeStripTurn()).toBe(false);
  });

  it("still answers once when the browser refuses sessionStorage", () => {
    vi.spyOn(window, "sessionStorage", "get").mockImplementation(() => {
      throw new Error("denied");
    });
    expect(takeStripTurn()).toBe(true);
    expect(takeStripTurn()).toBe(false);
  });
});
