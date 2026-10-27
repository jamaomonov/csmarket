/** Partners' copy in the admin: error codes, statuses, terms. */
import { type RewardStatus } from "./api";

import { errorText } from "@/features/users/labels";
import { ApiError } from "@/lib/api";

/** Above this percent the form warns: dear skins carry 2–3 % of margin. */
export const PERCENT_WARN = 2;
export const MARGIN_WARNING = "На скинах от $1 000 маржа может уйти в минус.";

const ERRORS: Record<string, string> = {
  code_taken: "Такой код уже занят.",
  code_invalid: "Код: латиница, цифры и дефис, 3–32 символа.",
  code_locked: "Код нельзя менять: по ссылке уже пришли люди.",
  partner_exists: "Этот аккаунт уже партнёр.",
  user_not_found: "Аккаунт не найден.",
  partner_not_found: "Партнёр не найден.",
};

export function referralErrorText(err: unknown): string {
  if (err instanceof ApiError && err.code !== undefined) {
    const known = ERRORS[err.code];
    if (known !== undefined) return known;
  }
  return errorText(err);
}

export const REWARD_STATUS: Record<RewardStatus, string> = {
  held: "В ожидании",
  credited: "Начислено",
  cancelled: "Отменено",
};

export function termText(months: number | null): string {
  return months === null ? "навсегда" : `${String(months)} мес.`;
}

export function percentText(percent: string): string {
  return `${Number(percent).toLocaleString("ru")} %`;
}
