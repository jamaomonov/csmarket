/** Operator-facing Russian labels of the «Обмены» table. */
import { type TradeSource, type TradeView } from "./kinds";

export const TRADE_VIEW_LABELS: Record<TradeView, string> = {
  all: "Все",
  active: "В пути",
  hold: "На защите",
  attention: "Требуют внимания",
  refunds: "Возвраты",
};

export const SOURCE_LABELS: Record<TradeSource, string> = {
  waxpeer: "Waxpeer",
  skinslink: "Skinslink",
  lisskins: "LIS-SKINS",
};
