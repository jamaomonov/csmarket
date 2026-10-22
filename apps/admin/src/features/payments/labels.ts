/** Operator-facing Russian labels for the payments pages. Unknown values fall back to the raw code. */
import { type KassaTxn } from "./api";
import { type PaymentPurpose } from "./kinds";

import { errorText } from "@/features/users/labels";
import { ApiError } from "@/lib/api";
import { formatSum } from "@/lib/format";

export const PURPOSE_LABELS: Record<PaymentPurpose, string> = {
  topup: "пополнение",
  order: "заказ",
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

const HOLD_ERRORS: Record<string, string> = {
  hold_decided: "Этот платёж уже решён — страница обновлена.",
  hold_not_found: "Платёж не найден — возможно, его уже убрали из очереди.",
};

/** A hold decision's error in words; anything else goes through the shared text. */
export function holdErrorText(err: unknown): string {
  if (err instanceof ApiError && err.code !== undefined) {
    const known = HOLD_ERRORS[err.code];
    if (known !== undefined) return known;
  }
  return errorText(err);
}
