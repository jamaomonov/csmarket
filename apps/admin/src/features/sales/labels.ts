/** «Выкуп»'s words for the operator (Russian). */
import { type AttentionFilter, type AttentionReason, type CardType, type SaleStatus } from "./api";
import { type PayoutFlag, type PayoutStatus } from "./payoutsApi";

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

export const ATTENTION_LABELS: Record<AttentionReason, string> = {
  rolled_back: "откат после выплаты — разобрать вручную",
  late_deposit: "закрыта, но Skinslink видит обмен — разобрать вручную",
  credit_blocked: "кошелёк заморожен — зачисление ждёт разморозки",
};

export const ATTENTION_FILTER_LABELS: Record<AttentionFilter, string> = {
  open: "ждут проверки",
  resolved: "проверены",
  any: "с пометкой",
};

/** A payout row's risk chips; `danger` ones block «Выплачено» or need a look. */
export const FLAG_LABELS: Record<PayoutFlag, { text: string; danger: boolean }> = {
  banned: { text: "аккаунт заблокирован", danger: true },
  wallet_frozen: { text: "кошелёк заморожен", danger: true },
  sell_blocked: { text: "выкуп запрещён", danger: true },
  shared_card: { text: "карта у других", danger: true },
  new_account: { text: "новый аккаунт", danger: false },
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

/** The last four of `•••• 9015`. */
export function last4(masked: string): string {
  return masked.replace(/\D/g, "").slice(-4);
}

/** 16 digits grouped by four. */
export function groupDigits(digits: string): string {
  return digits.replace(/(\d{4})(?=\d)/g, "$1 ");
}

const PAYOUT_ERRORS: Record<string, string> = {
  payout_not_payable: "Заявку уже нельзя изменить — страница обновлена.",
  payout_claimed: "Эту заявку уже платит другой администратор — страница обновлена.",
  payout_user_blocked:
    "Аккаунт заблокирован или кошелёк заморожен. Выплатить можно только с причиной.",
  wallet_frozen:
    "Кошелёк пользователя заморожен — вернуть деньги на баланс нельзя. Разморозьте или выплатите на карту.",
  balance_spent: "Пользователь уже потратил эти деньги — отменить отказ нельзя.",
  undo_expired: "Отменить уже нельзя: прошло больше 10 минут.",
  payout_not_cancelable: "Отменить можно только заявку, по которой был откат обмена.",
  settings_stale:
    "Настройки уже сохранил кто-то другой. Обновите страницу и внесите правки заново.",
  nothing_to_resolve: "У продажи нет пометки — проверять нечего.",
};

export function payoutErrorText(err: unknown): string {
  if (err instanceof ApiError && err.code !== undefined) {
    const known = PAYOUT_ERRORS[err.code];
    if (known !== undefined) return known;
  }
  return errorText(err);
}
