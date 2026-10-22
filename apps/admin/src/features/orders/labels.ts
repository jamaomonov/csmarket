/** The order's chip and its actions' errors in Russian; statuses and reasons are `lib/dictionary`. */
import { type OrderStatus } from "./kinds";

import { errorText } from "@/features/users/labels";
import { ApiError } from "@/lib/api";
import { formatDateTime } from "@/lib/format";

interface OrderChip {
  of: "order";
  code: OrderStatus | "accepted";
  sub?: string;
  title?: string;
}

/**
 * An order's chip: an accepted trade under Steam's protection reads «принят» with «защита до
 * DD.MM» under it (not stuck, a rollback is still possible), the same word as its trade row.
 */
export function orderChip(
  status: OrderStatus,
  protectedUntil: string | null = null,
  estimated = false,
): OrderChip {
  const running = protectedUntil !== null && new Date(protectedUntil).getTime() > Date.now();
  if (protectedUntil !== null && (status === "trade_sent" || (status === "delivered" && running))) {
    const approx = estimated ? "≈ " : "";
    return {
      of: "order",
      code: "accepted",
      sub: `защита до ${approx}${formatDateTime(protectedUntil).slice(0, 5)}`,
      title: `Покупатель принял обмен. Защита Steam до ${approx}${formatDateTime(protectedUntil)}, затем «получен».`,
    };
  }
  return { of: "order", code: status };
}

/** Order actions' 409s in Russian; the API's English `detail` is never shown for these. */
const ORDER_CODE_MESSAGES: Record<string, string> = {
  order_in_flight: "Скин ещё в пути — вернуть деньги нельзя.",
  already_refunded: "Деньги уже на балансе.",
  not_retryable: "Повтор сейчас невозможен.",
  waxpeer_buy_off: "Покупка на Waxpeer выключена — верните деньги или включите её.",
  order_needs_attention: "Сначала разберите обмен.",
  order_busy: "Покупка ещё идёт — попробуйте через минуту.",
  nothing_to_resolve: "Здесь нечего разбирать.",
  order_not_refundable: "Этот заказ нельзя вернуть.",
  waxpeer_unavailable: "Не удалось проверить покупку — попробуйте позже.",
  source_unavailable: "Поставщик не ответил — попробуйте позже.",
};

/** Codes that mean the page is stale: the caller refetches the order to show the real state. */
export function isOrderConflict(err: unknown): boolean {
  return err instanceof ApiError && err.status === 409;
}

export function orderErrorText(err: unknown): string {
  if (err instanceof ApiError && err.code !== undefined) {
    const known = ORDER_CODE_MESSAGES[err.code];
    if (known !== undefined) return known;
  }
  return errorText(err);
}
