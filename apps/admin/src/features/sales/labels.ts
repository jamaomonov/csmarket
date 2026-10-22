/** «Выкуп»'s words for the operator (Russian). */
import { type CardType } from "./api";
import { type PayoutFlag, type PayoutStatus } from "./payoutsApi";

import { errorText } from "@/features/users/labels";
import { ApiError } from "@/lib/api";

/** The queue's tabs (a tab names many requests: «Ждут 7 дней»); a chip is `Status of="payout"`. */
export const PAYOUT_TABS: Record<PayoutStatus, string> = {
  to_pay: "К выплате",
  waiting_hold: "Ждут 7 дней",
  paid: "Выплачено",
  rejected: "Отклонено",
  canceled: "Отменено",
};

/** A payout row's risk flags that block «Выплачено» or need a look (words: the dictionary). */
export const FLAG_DANGER: Record<PayoutFlag, boolean> = {
  banned: true,
  wallet_frozen: true,
  sell_blocked: true,
  shared_card: true,
  new_account: false,
  rolled_back: true,
  seller_reverted: true,
};

/** A payout's chip: a request canceled because the seller reverted the trade says so. */
export function payoutCode(
  status: PayoutStatus,
  flags: readonly PayoutFlag[] | null | undefined,
): PayoutStatus | "seller_reverted" {
  return status === "canceled" && (flags ?? []).includes("seller_reverted")
    ? "seller_reverted"
    : status;
}

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
  payout_sale_reverted:
    "Обмен по этой продаже отменён — скины вернулись к продавцу. Выплатить можно только с причиной.",
  wallet_frozen:
    "Кошелёк пользователя заморожен — вернуть деньги на баланс нельзя. Разморозьте или выплатите на карту.",
  balance_spent: "Пользователь уже потратил эти деньги — отменить отказ нельзя.",
  undo_expired: "Отменить уже нельзя: прошло больше 10 минут.",
  undo_not_yours:
    "Отменить «Выплачено» может только тот, кто его отметил: только он знает, ушёл ли перевод.",
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
