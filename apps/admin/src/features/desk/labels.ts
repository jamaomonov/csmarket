/** «Мои сделки»: Russian words for statuses and the API's refusals. */
import { type DealStatus, type ItemState, type Method } from "./api";

import { type Tone } from "@/components/StatusChip";
import { STEAM_REASONS } from "@/features/sales/labels";
import { ApiError } from "@/lib/api";

export const DEAL_STATUS: Record<DealStatus, { label: string; tone: Tone }> = {
  agreed: { label: "договорились", tone: "neutral" },
  paid: { label: "оплачено", tone: "progress" },
  received: { label: "скины получены", tone: "info" },
  closed: { label: "закрыта", tone: "success" },
  cancelled: { label: "отменена", tone: "muted" },
  reverted: { label: "трейдер откатил обмен", tone: "danger" },
};

/** An item's state in words; an open one reads by where it goes. */
export function itemState(state: ItemState, destination: "skinslink" | "stock"): string {
  if (state === "open") return destination === "stock" ? "на складе" : "ждёт отправки";
  return ITEM_STATE[state];
}

export const ITEM_STATE: Record<ItemState, string> = {
  open: "ждёт отправки",
  sent: "в обмене",
  credited: "Skinslink заплатил",
  sold: "продан",
  written_off: "списан",
  reverted: "откат",
};

export const METHOD: Record<Method, string> = {
  direct: "напрямую",
  guarantor: "через гаранта",
};

/** Skinslink's deposit statuses in words. */
export const DEPOSIT_STATUS: Record<string, string> = {
  creating: "отправляем…",
  new: "Skinslink принял заявку",
  pending: "бот готовит обмен",
  active: "обмен у трейдера",
  hold: "принят, Steam держит 7 дней",
  completed: "завершён",
  failed: "не прошёл",
  canceled: "отменён",
  reverted: "откат",
};

const CODES: Record<string, string> = {
  rate_required: "Для суммы в сумах нужен курс.",
  trade_link_invalid: "Это не трейд-ссылка Steam.",
  trade_link_missing: "У сделки нет трейд-ссылки.",
  prices_moved: "Цена Skinslink изменилась при отправке. Отправьте ещё раз.",
  skins_gone: "Этих скинов уже нет в инвентаре трейдера.",
  deposit_open: "Обмен по этой сделке уже идёт.",
  nothing_to_send: "Нечего отправлять: нет скинов, которые ждут отправки в Skinslink.",
  item_not_open: "Этот скин уже не ждёт: его продали, отправили или списали.",
  item_not_found: "Этого скина уже нет в сделке. Обновите страницу.",
  item_not_undoable: "Это уже не отменить: Skinslink заплатил за скин или трейдер откатил обмен.",
  last_item: "Это последний скин сделки. Чтобы закрыть её, смените статус на «отменена».",
  no_asset: "Этот скин нельзя отправить в Skinslink: его нет в инвентаре трейдера.",
  deal_busy:
    "Сейчас статус не сменить: идёт обмен или часть скинов уже продана, зачислена или списана.",
  desk_unavailable: "Skinslink сейчас не отвечает. Попробуйте через минуту.",
  price_required: "Сначала укажите, сколько заплатили за сделку.",
  price_locked: "Цену уже не изменить: часть скинов продана, зачислена или списана.",
  idempotency_mismatch: "Эта операция уже была выполнена с другими данными. Обновите страницу.",
};

export function deskErrorText(err: unknown): string {
  if (!(err instanceof ApiError)) return "Не получилось. Попробуйте ещё раз.";
  if (err.code === "steam_refused") {
    // Our problem+json body: narrowing the one field we read.
    const reason = (err.body as { reason?: string } | undefined)?.reason;
    return `Steam не даёт обмениваться: ${STEAM_REASONS[reason ?? ""] ?? "аккаунт не может обмениваться"}.`;
  }
  const known = err.code !== undefined ? CODES[err.code] : undefined;
  if (known !== undefined) return known;
  if (err.status === 503) return "Skinslink сейчас не отвечает. Попробуйте через минуту.";
  if (err.status === 422) return "Проверьте поля формы.";
  return "Не получилось. Попробуйте ещё раз.";
}
