/** The closed sets the orders API filters by (kept apart from `api.ts` so tests can mock that). */
export const ORDER_STATUSES = [
  "pending",
  "paid",
  "buying",
  "trade_sent",
  "delivered",
  "cancelled",
  "failed",
  "returned",
] as const;
export type OrderStatus = (typeof ORDER_STATUSES)[number];

export const ATTENTION_REASONS = [
  "buy_unconfirmed",
  "ambiguous_trade",
  "rolled_back",
  "source_forbidden",
  "audit_divergence",
] as const;
export type AttentionReason = (typeof ATTENTION_REASONS)[number];

export const FAILURE_REASONS = [
  "sold_out",
  "source_low_balance",
  "invalid_trade_link",
  "not_accepted",
  "trade_hold",
  "price_moved",
  "source_refused",
  "admin",
] as const;
export type FailureReason = (typeof FAILURE_REASONS)[number];
