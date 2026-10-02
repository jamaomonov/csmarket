/** Operator-facing Russian words for the pricing page; the API's English text is never shown. */
import { type Applied } from "./api";

import { ApiError } from "@/lib/api";

export const APPLIED: Record<Applied, string> = {
  formula: "по формуле",
  fixed: "ручная цена",
  min_margin: "минимальная маржа",
  steam_cap: "не дороже Steam",
  floor: "нижняя цена",
};

/** A refused rules document, in words an operator can act on. */
function rulesProblem(err: ApiError): string {
  const text = JSON.stringify(err.body ?? "");
  if (text.includes("retail")) return "Проверьте числа: брекеты должны идти по возрастанию от $0.";
  if (text.includes("liquidity")) {
    return "Проверьте полосы ликвидности: от большего числа лотов к меньшему, последняя — от 0.";
  }
  return "Проверьте числа в правилах: где-то значение вне допустимого.";
}

export function errorText(err: unknown): string {
  if (!(err instanceof ApiError)) return "Не получилось. Попробуйте ещё раз.";
  if (err.code === "idempotency_mismatch") {
    return "Эта операция уже была выполнена с другими данными. Обновите страницу.";
  }
  if (err.status === 422) return rulesProblem(err);
  if (err.status === 404) return "Скин не найден.";
  if (err.status === 403) return "Нет доступа.";
  return "Не получилось. Попробуйте ещё раз.";
}
