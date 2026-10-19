/** Operator-facing Russian labels of the «Обмены» table. */
import { type TradeRowState, type TradeSource, type TradeView } from "./kinds";

import { type Tone } from "@/components/StatusChip";

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
/** One tone per state (refunds neutral: the money went back, the case is closed). */
export const STATE_TONE: Record<TradeRowState, Tone> = {
  pending: "muted",
  buying: "progress",
  sent: "progress",
  hold: "info",
  delivered: "success",
  refunded: "neutral",
  cancelled: "muted",
  failed_held: "danger",
};

export const SOURCE_LABELS: Record<TradeSource, string> = {
  waxpeer: "Waxpeer",
  skinslink: "Skinslink",
  lisskins: "LIS-SKINS",
};
