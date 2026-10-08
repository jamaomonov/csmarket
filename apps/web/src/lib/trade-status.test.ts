import { describe, expect, it } from "vitest";

import { orderBadge, orderReceived, saleBadge } from "./trade-status";

import { orderOut, tradeOut } from "@/test/orders";
import { saleOut } from "@/test/sales";

describe("orderBadge", () => {
  it("reads «Получен» for a trade accepted while the order is still trade_sent", () => {
    const order = orderOut("A", { status: "trade_sent", trade: tradeOut({ state: "accepted" }) });
    expect(orderReceived(order)).toBe(true);
    expect(orderBadge(order)).toEqual({ tone: "ok", key: "orders.status.delivered" });
  });

  it("keeps «Обмен отправлен» while the offer waits", () => {
    const order = orderOut("A", { status: "trade_sent", trade: tradeOut({ state: "offer_sent" }) });
    expect(orderBadge(order)).toEqual({ tone: "run", key: "orders.status.trade_sent" });
  });

  it("names the refund on a failed order the money came back from", () => {
    expect(orderBadge(orderOut("A", { status: "failed", refunded_to: "balance" }))).toEqual({
      tone: "bad",
      key: "trades.refunded",
    });
    expect(orderBadge(orderOut("A", { status: "returned" })).key).toBe("orders.status.returned");
  });

  it("is grey for a cancelled order and yellow for an unpaid one", () => {
    expect(orderBadge(orderOut("A", { status: "cancelled" })).tone).toBe("muted");
    expect(orderBadge(orderOut("A")).tone).toBe("wait");
  });
});

describe("saleBadge", () => {
  it("names the money's day while the sale is in hold", () => {
    expect(saleBadge(saleOut("S"))).toEqual({
      tone: "wait",
      key: "trades.moneyOn",
      date: "2026-10-15T16:14:00Z",
    });
  });

  it("reads a card sale's payout", () => {
    const paid = saleOut("S", { status: "payout", payout_status: "paid" });
    expect(saleBadge(paid)).toEqual({ tone: "ok", key: "sales.payout.paid" });
    const waiting = saleOut("S", { status: "payout", payout_status: "waiting_hold" });
    expect(saleBadge(waiting).key).toBe("trades.moneyOn");
  });

  it("is red for a reverted sale, green for a credited one", () => {
    expect(saleBadge(saleOut("S", { status: "reverted" })).tone).toBe("bad");
    expect(saleBadge(saleOut("S", { status: "credited" })).tone).toBe("ok");
  });
});
