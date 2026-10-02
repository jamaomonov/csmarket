import { describe, expect, it } from "vitest";

import { BALANCE, ORDERS, orderPath } from "./paths";

describe("order paths", () => {
  it("escapes the order number as one path segment", () => {
    expect(orderPath("A1B2C3")).toBe("/orders/A1B2C3");
    expect(orderPath("a/b?c")).toBe("/orders/a%2Fb%3Fc");
  });

  it("names the account pages", () => {
    expect(ORDERS).toBe("/account/orders");
    expect(BALANCE).toBe("/account/balance");
  });
});
