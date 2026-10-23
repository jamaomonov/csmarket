/** Operator words for «Отзывы». */
import { assertNever } from "@csmarket/utils";

import type { AdminReview, ReviewKind, ReviewLocale, ReviewTab } from "./api";

export const TABS: readonly ReviewTab[] = ["bad", "all", "good"];
export const KINDS: readonly ReviewKind[] = ["market", "sale"];
export const LOCALES: readonly ReviewLocale[] = ["ru", "uz", "en"];

export const TAB_LABELS: Record<ReviewTab, string> = {
  bad: "Плохие",
  all: "Все",
  good: "Хорошие",
};
export const KIND_LABELS: Record<ReviewKind, string> = { market: "Маркет", sale: "Выкуп" };
export const LOCALE_LABELS: Record<ReviewLocale, string> = {
  ru: "Русский",
  uz: "Oʻzbekcha",
  en: "English",
};

/** The order's or the sale's admin page. */
export function dealPath(r: Pick<AdminReview, "kind" | "number">): string {
  switch (r.kind) {
    case "market":
      return `/orders/${encodeURIComponent(r.number)}`;
    case "sale":
      return `/sales/${encodeURIComponent(r.number)}`;
    default:
      return assertNever(r.kind);
  }
}
