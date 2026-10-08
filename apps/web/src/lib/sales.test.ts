import { describe, expect, it } from "vitest";

import { salePollInterval, type SaleOut } from "./sales";

const sale = (over: Partial<SaleOut>): SaleOut => ({
  number: "S7K2M9QX",
  status: "offered",
  payout_to: "balance",
  card: null,
  items_uzs: "155200",
  bonus_uzs: "3100",
  fee_uzs: "0",
  payout_uzs: "158300",
  items: [],
  offer: null,
  money_at: null,
  payout_status: null,
  payout_reject_reason: null,
  created_at: "2026-10-08T10:00:00Z",
  ...over,
});

describe("salePollInterval", () => {
  it("asks often while the offer is out, rarely while the money waits, never once settled", () => {
    expect(salePollInterval(sale({ status: "creating" }))).toBe(5_000);
    expect(salePollInterval(sale({ status: "offered" }))).toBe(5_000);
    expect(salePollInterval(sale({ status: "hold" }))).toBe(60_000);
    expect(salePollInterval(sale({ status: "payout", payout_status: "to_pay" }))).toBe(60_000);
    expect(salePollInterval(sale({ status: "payout", payout_status: "paid" }))).toBe(false);
    expect(salePollInterval(sale({ status: "credited" }))).toBe(false);
    expect(salePollInterval(undefined)).toBe(false);
  });
});
