/** Operator-facing Russian labels for the users pages. Unknown values fall back to the raw code. */
import { assertNever } from "@csmarket/utils";

import { type AdminUserDetail, type TopupStatus } from "./api";

import { ApiError, formatApiError } from "@/lib/api";

/** Known problem+json codes in Russian; the API's English `detail` is never shown for these. */
const CODE_MESSAGES: Record<string, string> = {
  idempotency_mismatch: "Эта операция уже была выполнена с другими данными. Обновите страницу.",
  balance_too_low: "На балансе меньше, чем вы хотите списать.",
  ban_self: "Себя заблокировать нельзя.",
  ban_admin: "Администратора заблокировать нельзя.",
  already_banned: "Пользователь уже заблокирован.",
  not_banned: "Пользователь уже разблокирован.",
};

/** 409s meaning the card is stale (someone else changed the ban): close and refresh. */
export const STALE_BAN_CODES: ReadonlySet<string> = new Set(["already_banned", "not_banned"]);

/** A 422 the page has no words for (e.g. a filter the API refused): never its raw detail. */
const UNPROCESSABLE = "Запрос не принят: проверьте введённые значения и фильтры.";

export function errorText(err: unknown): string {
  if (!(err instanceof ApiError)) return "Не получилось. Попробуйте ещё раз.";
  const known = err.code !== undefined ? CODE_MESSAGES[err.code] : undefined;
  if (known !== undefined) return known;
  return err.status === 422 ? UNPROCESSABLE : formatApiError(err);
}

export function roleLabel(roles: string[]): string {
  return roles.includes("admin") ? "администратор" : "покупатель";
}

const KINDS: Record<string, string> = {
  topup: "Пополнение",
  topup_reversal: "Отмена пополнения",
  admin_adjust: "Изменение администратором",
};

export function kindLabel(kind: string): string {
  return KINDS[kind] ?? kind;
}

const TOPUP_STATUSES: Record<TopupStatus, string> = {
  pending: "ждёт оплаты",
  succeeded: "зачислено",
  expired: "истекло",
  reversed: "отменено кассой",
};

export function topupStatusLabel(status: TopupStatus): string {
  return TOPUP_STATUSES[status];
}

const PROVIDERS: Record<string, string> = {
  click: "Click",
  payme: "Payme",
  uzum: "Uzum",
  mock: "тестовая",
};

export function providerLabel(provider: string | null): string {
  return provider === null ? "—" : (PROVIDERS[provider] ?? provider);
}

const LOCALES: Record<AdminUserDetail["locale"], string> = {
  ru: "русский",
  uz: "узбекский",
  en: "английский",
};

export function localeLabel(locale: AdminUserDetail["locale"]): string {
  return LOCALES[locale];
}

const TRADE_REASONS: Record<NonNullable<AdminUserDetail["trade_link_reason"]>, string> = {
  invalid: "ссылка неверна",
  private: "инвентарь скрыт",
  trade_ban: "бан на обмен в Steam",
  hold: "задержка обмена (нет Steam Guard)",
  unavailable: "Steam не ответил",
};

/** The trade-link check in one line, e.g. «есть ограничения: задержка обмена». */
export function tradeVerdictText(user: AdminUserDetail): string {
  const reason = user.trade_link_reason ? TRADE_REASONS[user.trade_link_reason] : null;
  switch (user.trade_link_verdict) {
    case null:
      return "не проверялась";
    case "ok":
      return "работает";
    case "warn":
      return reason ? `есть ограничения: ${reason}` : "есть ограничения";
    case "bad":
      return reason ? `не работает: ${reason}` : "не работает";
    default:
      return assertNever(user.trade_link_verdict);
  }
}
