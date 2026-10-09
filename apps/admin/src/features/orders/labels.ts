/** Operator-facing Russian labels for the order page and the order rows. Unknown codes show raw. */
import { type AttentionReason, type FailureReason, type OrderStatus } from "./kinds";

import { errorText } from "@/features/users/labels";
import { ApiError } from "@/lib/api";

export const STATUS_LABELS: Record<OrderStatus, string> = {
  pending: "ждёт оплаты",
  paid: "оплачен",
  buying: "покупаем",
  trade_sent: "обмен отправлен",
  delivered: "получен",
  cancelled: "отменён",
  failed: "не получилось",
  returned: "обмен не состоялся",
};

/** Tailwind classes of the status chip. */
export const STATUS_CHIP: Record<OrderStatus, string> = {
  pending: "bg-surface-2 text-fg-muted",
  paid: "bg-warning/15 text-warning",
  buying: "bg-warning/15 text-warning",
  trade_sent: "bg-warning/15 text-warning",
  delivered: "bg-success/15 text-success",
  cancelled: "bg-surface-2 text-fg-muted",
  failed: "bg-danger/15 text-danger",
  returned: "bg-danger/15 text-danger",
};

export const ATTENTION_LABELS: Record<AttentionReason, string> = {
  buy_unconfirmed: "ответ площадки потерян",
  ambiguous_trade: "несколько обменов",
  rolled_back: "откат после получения",
  source_forbidden: "Площадка: IP не в белом списке",
  audit_divergence: "расхождение со сверкой",
};

export const FAILURE_LABELS: Record<FailureReason, string> = {
  sold_out: "скин продан",
  source_low_balance: "не хватило денег на площадке",
  invalid_trade_link: "неверная трейд-ссылка",
  not_accepted: "обмен не принят",
  trade_hold: "задержка обменов Steam",
  price_moved: "цена поставщика выросла",
  admin: "вернул администратор",
};

/** Waxpeer's trade status codes we know (`orders.trades`); any other shows as a bare code. */
export function waxpeerStatusLabel(status: number | null): string {
  switch (status) {
    case null:
      return "—";
    case 4:
      return "4 — предложение отправлено";
    case 5:
      return "5 — выдан покупателю";
    case 6:
      return "6 — не состоялся";
    default:
      return String(status);
  }
}

/** Order actions' 409s in Russian; the API's English `detail` is never shown for these. */
const ORDER_CODE_MESSAGES: Record<string, string> = {
  order_in_flight: "Скин ещё в пути — вернуть деньги нельзя.",
  already_refunded: "Деньги уже на балансе.",
  not_retryable: "Повтор сейчас невозможен.",
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
