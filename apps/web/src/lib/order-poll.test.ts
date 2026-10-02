import { afterEach, describe, expect, it, vi } from "vitest";

import { orderPollInterval } from "./order-poll";

import type { OrderStatus } from "./orders";

afterEach(() => {
  vi.restoreAllMocks();
});

function withRandom(value: number): void {
  vi.spyOn(Math, "random").mockReturnValue(value);
}

describe("orderPollInterval", () => {
  it.each<[OrderStatus]>([["pending"], ["paid"], ["buying"], ["trade_sent"]])(
    "polls a %s order every 8 s before jitter",
    (status) => {
      withRandom(0);
      expect(orderPollInterval(status, 0)).toBe(8_000);
    },
  );

  it.each<[OrderStatus]>([["delivered"], ["cancelled"], ["failed"], ["returned"]])(
    "stops on a %s order: nothing left to wait for",
    (status) => {
      expect(orderPollInterval(status, 0)).toBe(false);
      expect(orderPollInterval(status, 5)).toBe(false);
    },
  );

  it.each([
    [0, 8_000],
    [1, 16_000],
    [2, 32_000],
    [3, 60_000],
    [10, 60_000],
  ])("backs off ×2 per failure up to ×8 and the 60 s cap (%i failures)", (failures, ms) => {
    withRandom(0);
    expect(orderPollInterval("buying", failures)).toBe(ms);
  });

  it("jitters up to ×2, capped after jittering", () => {
    withRandom(0.5);
    expect(orderPollInterval("trade_sent", 0)).toBe(12_000);
    withRandom(0.999);
    expect(orderPollInterval("trade_sent", 1)).toBe(31_984);
    expect(orderPollInterval("trade_sent", 2)).toBe(60_000);
  });

  it("treats a negative or fractional failure count as none / whole", () => {
    withRandom(0);
    expect(orderPollInterval("paid", -1)).toBe(8_000);
    expect(orderPollInterval("paid", 1.7)).toBe(16_000);
  });
});
