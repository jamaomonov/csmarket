import { describe, expect, it } from "vitest";

import { orderPath, TRADES, TRANSACTIONS } from "./paths";

describe("order paths", () => {
  it("escapes the order number as one path segment", () => {
    expect(orderPath("A1B2C3")).toBe("/orders/A1B2C3");
    expect(orderPath("a/b?c")).toBe("/orders/a%2Fb%3Fc");
  });

  it("names the account pages", () => {
    expect(TRADES).toBe("/account/trades");
    expect(TRANSACTIONS).toBe("/account/transactions");
  });
});
