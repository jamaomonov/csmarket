/** Operator-facing Russian labels of the «Обмены» table. */
import { type TradeRowState, type TradeSource, type TradeView } from "./kinds";

export const TRADE_VIEW_LABELS: Record<TradeView, string> = {
  all: "Все",
  active: "В пути",
  hold: "На холде",
  attention: "Требуют внимания",
  refunds: "Возвраты",
};

export const STATE_LABELS: Record<TradeRowState, string> = {
  pending: "ждёт оплаты",
  buying: "покупаем",
  sent: "отправлен",
  hold: "на холде",
  delivered: "получен",
  refunded: "возврат",
  cancelled: "отменён",
  failed_held: "не получилось",
};

/** Tailwind classes of the state chip. */
export const STATE_CHIP: Record<TradeRowState, string> = {
  pending: "bg-surface-2 text-fg-muted",
  buying: "bg-warning text-warning-fg",
  sent: "bg-warning text-warning-fg",
  hold: "bg-accent-subtle text-accent",
  delivered: "bg-success text-success-fg",
  refunded: "bg-surface-2 text-fg",
  cancelled: "bg-surface-2 text-fg-muted",
  failed_held: "bg-danger text-danger-fg",
};

export const SOURCE_LABELS: Record<TradeSource, string> = {
  waxpeer: "Waxpeer",
  skinslink: "Skinslink",
  lisskins: "LIS-SKINS",
};
