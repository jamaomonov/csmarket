/**
 * How often the order page re-reads its order.
 *
 * Polling is the reconciler: the order socket (`lib/realtime.ts`, M4b) only nudges a re-read
 * sooner. A socket can stay "connected" while it is dead (a backgrounded tab, a WebView
 * suspended during the hop to the bank), and a push lost in it must not leave the buyer
 * staring at «Покупаем» — so the poll runs until the order can no longer change.
 *
 * - an 8 s base: a crowd of open order pages stays cheap;
 * - ×2 per consecutive failure, up to ×8: an API that is refusing is not knocked on at
 *   the same rate;
 * - jitter ×(1..2): pages that failed together do not retry together;
 * - a 60 s cap, applied after the jitter, so a recovered API is noticed within a minute.
 */
import type { OrderStatus } from "./orders";

const BASE_MS = 8_000;
const MAX_MS = 60_000;
const MAX_DOUBLINGS = 3;

/** Statuses an order never leaves: the page stops polling. */
const TERMINAL: ReadonlySet<OrderStatus> = new Set([
  "delivered",
  "cancelled",
  "failed",
  "returned",
]);

/**
 * @param status the order's status as last read.
 * @param failures consecutive failed reads (TanStack's `query.state.fetchFailureCount`).
 * @returns milliseconds until the next read, or `false` to stop.
 */
export function orderPollInterval(status: OrderStatus, failures: number): number | false {
  if (TERMINAL.has(status)) return false;
  const doublings = Math.min(Math.max(Math.floor(failures), 0), MAX_DOUBLINGS);
  const backoff = Math.min(BASE_MS * 2 ** doublings, MAX_MS);
  return Math.min(Math.round(backoff * (1 + Math.random())), MAX_MS);
}
