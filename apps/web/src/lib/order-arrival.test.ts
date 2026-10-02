import { describe, expect, it } from "vitest";

import { arrivalKassa, orderArrivalPath } from "./order-arrival";

describe("orderArrivalPath", () => {
  it("asks the order page to open the chosen kassa once", () => {
    expect(orderArrivalPath("A100", "click")).toBe("/orders/A100?go=1&via=click");
    expect(orderArrivalPath("A100", "mock")).toBe("/orders/A100?go=1&via=mock");
  });

  it("a balance payment or a paid replay lands on the plain page", () => {
    expect(orderArrivalPath("A100", "wallet")).toBe("/orders/A100");
    expect(orderArrivalPath("A100", null)).toBe("/orders/A100");
  });
});

describe("arrivalKassa", () => {
  it("reads the kassa the buyer chose", () => {
    expect(arrivalKassa("?go=1&via=payme")).toBe("payme");
    expect(arrivalKassa("?via=uzum")).toBe("uzum");
  });

  it("the test kassa's own return (?mock=1) means the test kassa", () => {
    expect(arrivalKassa("?mock=1")).toBe("mock");
    expect(arrivalKassa("?mock=1&go=1")).toBe("mock");
  });

  it("ignores the balance, unknown methods and a bare address", () => {
    for (const search of ["", "?go=1", "?via=wallet", "?via=paypal", "?via=", "?mock=0"]) {
      expect(arrivalKassa(search)).toBeNull();
    }
  });
});
