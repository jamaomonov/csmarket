/** The closed sets of the «Обмены» table (kept apart from `api.ts` so tests can mock that). */
export const TRADE_VIEWS = ["all", "active", "hold", "attention", "refunds"] as const;
export type TradeView = (typeof TRADE_VIEWS)[number];

/** One state vocabulary for every source (`orders.trade_row` on the API). */
export type TradeRowState =
  "pending" | "buying" | "sent" | "hold" | "delivered" | "refunded" | "cancelled" | "failed_held";

export type TradeSource = "waxpeer" | "skinslink" | "lisskins";
