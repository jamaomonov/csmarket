/** Operator-facing Russian labels for the API-keys pages. */
import { type LimitName, type Tariff } from "./api";

import { ApiError, formatApiError } from "@/lib/api";

const CODE_MESSAGES: Record<string, string> = {
  idempotency_mismatch: "Эта операция уже была выполнена с другими данными. Обновите страницу.",
  api_key_revoked: "Ключ уже отозван.",
  tariff_unchanged: "Этот тариф уже выбран.",
  limits_unchanged: "Эти лимиты уже заданы.",
};

const UNPROCESSABLE = "Запрос не принят: проверьте введённые значения.";

export function errorText(err: unknown): string {
  if (!(err instanceof ApiError)) return "Не получилось. Попробуйте ещё раз.";
  const known = err.code !== undefined ? CODE_MESSAGES[err.code] : undefined;
  if (known !== undefined) return known;
  return err.status === 422 ? UNPROCESSABLE : formatApiError(err);
}

export function tariffLabel(tariff: Tariff): string {
  return tariff === "cost" ? "по себестоимости" : "розница";
}

const DELIVERY: Record<string, string> = {
  pending: "ждёт отправки",
  sent: "доставлено",
  failed: "не доставлено",
};

export function deliveryLabel(status: string): string {
  return DELIVERY[status] ?? status;
}

export const LIMIT_LABELS: Record<LimitName, string> = {
  read_per_min: "Чтение",
  orders_per_min: "Заказы",
  feed_per_min: "Фид",
  check_per_min: "Проверка трейд-ссылки",
};

/** What a key gets when it sets no limit of its own. */
export const LIMIT_DEFAULTS: Record<LimitName, number> = {
  read_per_min: 60,
  orders_per_min: 10,
  feed_per_min: 1,
  check_per_min: 30,
};

export const LIMIT_NAMES: LimitName[] = [
  "read_per_min",
  "orders_per_min",
  "feed_per_min",
  "check_per_min",
];
