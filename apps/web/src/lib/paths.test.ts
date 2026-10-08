import { describe, expect, it } from "vitest";

import { orderPath, salePath, TRADES, TRANSACTIONS } from "./paths";

describe("order paths", () => {
  it("escapes the order number as one path segment", () => {
    expect(orderPath("A1B2C3")).toBe("/orders/A1B2C3");
    expect(orderPath("a/b?c")).toBe("/orders/a%2Fb%3Fc");
  });

  it("escapes the sale number as one path segment", () => {
    expect(salePath("S7K2M9QX")).toBe("/account/sales/S7K2M9QX");
    expect(salePath("a/b")).toBe("/account/sales/a%2Fb");
  });

  it("names the account pages", () => {
    expect(TRADES).toBe("/account/trades");
    expect(TRANSACTIONS).toBe("/account/transactions");
  });
});
