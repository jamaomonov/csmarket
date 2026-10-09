/** Operator-facing Russian labels for the API-keys pages. */
import { type Tariff } from "./api";

import { ApiError, formatApiError } from "@/lib/api";

const CODE_MESSAGES: Record<string, string> = {
  idempotency_mismatch: "Эта операция уже была выполнена с другими данными. Обновите страницу.",
  api_key_revoked: "Ключ уже отозван.",
  tariff_unchanged: "Этот тариф уже выбран.",
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
