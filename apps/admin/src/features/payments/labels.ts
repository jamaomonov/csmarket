/** Operator-facing Russian labels for the payments pages. Unknown values fall back to the raw code. */
import { type KassaTxn } from "./api";
import { type PaymentPurpose, type PaymentStatus } from "./kinds";

import { formatSum } from "@/lib/format";

export const STATUS_LABELS: Record<PaymentStatus, string> = {
  created: "создан",
  pending: "ждёт кассу",
  succeeded: "оплачен",
  failed: "не прошёл",
  cancelled: "отменён",
  refunded: "возвращён",
};

export const PURPOSE_LABELS: Record<PaymentPurpose, string> = {
  topup: "пополнение",
  order: "заказ",
};

/** Tailwind classes of the status chip. */
export const STATUS_CHIP: Record<PaymentStatus, string> = {
  created: "bg-surface-2 text-fg-muted",
  pending: "bg-warning text-warning-fg",
  succeeded: "bg-success text-success-fg",
  failed: "bg-danger text-danger-fg",
  cancelled: "bg-surface-2 text-fg-muted",
  refunded: "bg-surface-2 text-fg",
};

const KASSA_STATUSES: Record<string, string> = {
  PREPARED: "подготовлен",
  CONFIRMED: "подтверждён",
  CANCELLED: "отменён",
  created: "создана",
  performed: "проведена",
  cancelled: "отменена",
  cancelled_after_perform: "отменена после проведения",
  CREATED: "создана",
  REVERSED: "возвращена",
  FAILED: "не прошла",
};

export function kassaStatusLabel(status: string): string {
  return KASSA_STATUSES[status] ?? status;
}

/** Digits grouped by thousands with a no-break space (no float round trip). */
function groupDigits(digits: string): string {
  return digits.replace(/\B(?=(\d{3})+(?!\d))/g, "\u00a0");
}

/** `50000` soʻm -> `50 000 сум`; `5000000` tiyin -> `5 000 000 тийин`. Never converted. */
export function formatKassaAmount(txn: Pick<KassaTxn, "amount" | "amount_unit">): string {
  return txn.amount_unit === "soum"
    ? formatSum(txn.amount)
    : `${groupDigits(txn.amount)}\u00a0тийин`;
}

/** The only `extra` keys the detail renders, in order, with their labels. */
export const EXTRA_LABELS: readonly (readonly [string, string])[] = [
  ["account", "Счёт"],
  ["service_id", "Сервис"],
  ["click_paydoc_id", "Платёж Click"],
  ["reason", "Причина"],
  ["source", "Источник"],
  ["phone", "Телефон"],
];

/** A run of five digits is a phone number leaking through; the API masks it, so never show it. */
export function safeExtraValue(key: string, value: string): string {
  return key === "phone" && /\d{5,}/.test(value) ? "скрыт" : value;
}
