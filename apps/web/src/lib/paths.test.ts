import { describe, expect, it } from "vitest";

import { CARDS, orderPath, salePath, TRADES, TRANSACTIONS } from "./paths";

describe("order paths", () => {
  it("escapes the order number as one path segment", () => {
    expect(orderPath("A1B2C3")).toBe("/orders/A1B2C3");
    expect(orderPath("a/b?c")).toBe("/orders/a%2Fb%3Fc");
  });

  it("escapes the sale number and names the cards page", () => {
    expect(salePath("S7K2M9QX")).toBe("/account/sales/S7K2M9QX");
    expect(salePath("a/b")).toBe("/account/sales/a%2Fb");
    expect(CARDS).toBe("/account/cards");
  });

  it("names the account pages", () => {
    expect(TRADES).toBe("/account/trades");
    expect(TRANSACTIONS).toBe("/account/transactions");
  });
});
