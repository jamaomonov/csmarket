/** «Выкуп»'s words for the operator (Russian). */
import { type CardType, type PayoutStatus, type SaleStatus } from "./api";

import { errorText } from "@/features/users/labels";
import { ApiError } from "@/lib/api";

export const PAYOUT_LABELS: Record<PayoutStatus, string> = {
  to_pay: "К выплате",
  waiting_hold: "Ждут 7 дней",
  paid: "Выплачено",
  rejected: "Отклонено",
  canceled: "Отменено",
};

export const SALE_LABELS: Record<SaleStatus, string> = {
  creating: "создаётся",
  offered: "обмен отправлен",
  hold: "холд 7 дней",
  credited: "зачислено на баланс",
  payout: "выплата на карту",
  closed: "закрыта",
  reverted: "откат обмена",
};

export const ATTENTION_LABELS: Record<string, string> = {
  rolled_back: "откат после выплаты — разобрать вручную",
  late_deposit: "закрыта, но Skinslink видит обмен — разобрать вручную",
  credit_blocked: "кошелёк заморожен — зачисление ждёт разморозки",
};

export const CARD_BRANDS: Record<CardType, string> = {
  uzcard: "Uzcard",
  humo: "Humo",
  uzum_visa: "Uzum Visa",
};

/** `•••• 9015` with the brand: «Humo •••• 9015». */
export function cardLabel(type: CardType | null, masked: string | null): string {
  return type && masked ? `${CARD_BRANDS[type]} ${masked}` : "—";
}

/** 16 digits grouped by four. */
export function groupDigits(digits: string): string {
  return digits.replace(/(\d{4})(?=\d)/g, "$1 ");
}

export function payoutErrorText(err: unknown): string {
  if (err instanceof ApiError && err.code === "payout_not_payable") {
    return "Заявку уже нельзя изменить — страница обновлена.";
  }
  return errorText(err);
}
