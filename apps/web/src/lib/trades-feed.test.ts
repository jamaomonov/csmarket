import { describe, expect, it } from "vitest";

import { mergeTrades } from "./trades-feed";

import { orderOut } from "@/test/orders";
import { saleOut } from "@/test/sales";

const order = (n: string, at: string) => orderOut(n, { created_at: at });
const sale = (n: string, at: string) => saleOut(n, { created_at: at });
const keys = (m: ReturnType<typeof mergeTrades>) =>
  m.entries.map((e) => (e.kind === "order" ? e.order.number : e.sale.number));

describe("mergeTrades", () => {
  it("interleaves both streams newest first when both are complete", () => {
    const m = mergeTrades(
      {
        items: [order("O2", "2026-10-08T15:50:00Z"), order("O1", "2026-10-08T15:40:00Z")],
        hasMore: false,
      },
      {
        items: [sale("S1", "2026-10-08T16:12:00Z"), sale("S0", "2026-10-01T10:00:00Z")],
        hasMore: false,
      },
    );
    expect(keys(m)).toEqual(["S1", "O2", "O1", "S0"]);
    expect(m.next).toEqual([]);
  });

  it("holds back what an unloaded page of the other stream could precede", () => {
    const m = mergeTrades(
      { items: [order("O2", "2026-10-08T15:50:00Z")], hasMore: true },
      {
        items: [sale("S1", "2026-10-08T16:12:00Z"), sale("S0", "2026-10-01T10:00:00Z")],
        hasMore: false,
      },
    );
    expect(keys(m)).toEqual(["S1", "O2"]);
    expect(m.next).toEqual(["orders"]);
  });

  it("is empty with nothing loaded", () => {
    expect(mergeTrades({ items: [], hasMore: false }, { items: [], hasMore: false })).toEqual({
      entries: [],
      next: [],
    });
  });
});
