import type { OrderOut, SkinTradeOut } from "@/lib/orders";

/** An order as `GET /orders/{number}` answers it; tests override what they need. */
export function orderOut(number: string, over: Partial<OrderOut> = {}): OrderOut {
  return {
    number,
    status: "pending",
    slug: "ak-47-redline-field-tested",
    name: "AK-47 | Redline (Field-Tested)",
    phase: null,
    image_url: null,
    price_uzs: "381000",
    price_usd: "30.000000",
    created_at: "2026-10-02T10:00:00Z",
    expires_at: "2026-10-02T10:15:00Z",
    paid_at: null,
    delivered_at: null,
    paid_with: null,
    refunded_to: null,
    payable: true,
    trade: null,
    ...over,
  };
}

export function tradeOut(over: Partial<SkinTradeOut> = {}): SkinTradeOut {
  return {
    state: "buying",
    reason_code: null,
    offer_url: null,
    send_until: null,
    release_date: null,
    seller: null,
    refunded_to: null,
    ...over,
  };
}
