/**
 * One look for every trade on «Обмены», the order page and the sale page: a tone (the
 * badge's colour) and a message key under `web`. Green — the skin or the money is with
 * the user; yellow — waiting on time; blue — something is moving (or the user should
 * act); red — it did not happen; grey — nothing happened.
 */
import { assertNever } from "@csmarket/utils";

import type { OrderOut } from "./orders";
import type { SaleOut } from "./sales";

export type Tone = "ok" | "wait" | "run" | "bad" | "muted";

export interface Badge {
  tone: Tone;
  /** A key under the `web` messages. */
  key: string;
  /** The date the message names (`{date}`), ISO. */
  date?: string;
}

/** The skin is with the buyer: the trade was accepted, whatever the order row still says. */
export function orderReceived(order: OrderOut): boolean {
  if (order.status === "delivered") return true;
  const state = order.trade?.state;
  return order.status === "trade_sent" && (state === "accepted" || state === "released");
}

/** An order's badge. A Skinslink order in Steam's hold already reads «Получен». */
export function orderBadge(order: OrderOut): Badge {
  if (orderReceived(order)) return { tone: "ok", key: "orders.status.delivered" };
  switch (order.status) {
    case "pending":
      return { tone: "wait", key: "orders.status.pending" };
    case "paid":
    case "buying":
      return { tone: "run", key: "orders.status.buying" };
    case "trade_sent":
      return { tone: "run", key: "orders.status.trade_sent" };
    case "delivered":
      return { tone: "ok", key: "orders.status.delivered" };
    case "cancelled":
      return { tone: "muted", key: "orders.status.cancelled" };
    case "failed":
    case "returned":
      return {
        tone: "bad",
        key:
          order.refunded_to === "balance"
            ? order.channel === "api"
              ? "trades.refundedUsdWallet"
              : "trades.refunded"
            : `orders.status.${order.status}`,
      };
    default:
      return assertNever(order.status);
  }
}

/** A sale's badge; the money's date is named while it waits. */
export function saleBadge(sale: SaleOut): Badge {
  const due = (): Badge =>
    sale.money_at
      ? { tone: "wait", key: "trades.moneyOn", date: sale.money_at }
      : { tone: "wait", key: "sales.status.hold" };
  switch (sale.status) {
    case "creating":
      return { tone: "run", key: "sales.status.creating" };
    case "offered":
      return { tone: "run", key: "sales.status.offered" };
    case "hold":
      return due();
    case "credited":
      return { tone: "ok", key: "sales.status.credited" };
    case "payout":
      switch (sale.payout_status) {
        case "waiting_hold":
          return due();
        case "paid":
          return { tone: "ok", key: "sales.payout.paid" };
        case "rejected":
          return { tone: "ok", key: "sales.payout.rejected" };
        case "canceled":
          return { tone: "muted", key: "sales.payout.canceled" };
        case "to_pay":
        case null:
          return { tone: "run", key: "sales.status.payout" };
        default:
          return assertNever(sale.payout_status);
      }
    case "closed":
      return { tone: "muted", key: "sales.status.closed" };
    case "reverted":
      return { tone: "bad", key: "sales.status.reverted" };
    default:
      return assertNever(sale.status);
  }
}

/** The day a date falls on, «15 окт.». */
export function shortDay(locale: string, iso: string): string {
  return new Intl.DateTimeFormat(locale, { day: "numeric", month: "short" }).format(new Date(iso));
}
