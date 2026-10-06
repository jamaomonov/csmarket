"use client";

import { Chip, inputClass, selectClass, cn } from "@csmarket/ui";
import { CheckCheck, RefreshCw, Search, X } from "lucide-react";
import { useTranslations } from "next-intl";

export type SellSort = "expensive" | "cheap" | "name";

interface SellToolbarProps {
  query: string;
  onQuery: (q: string) => void;
  sort: SellSort;
  onSort: (s: SellSort) => void;
  categories: string[];
  category: string | null;
  onCategory: (c: string | null) => void;
  allChosen: boolean;
  onToggleAll: () => void;
}

/** Search, sort, select-all / clear, refresh, and the category chips. */
export function SellToolbar(p: SellToolbarProps) {
  const t = useTranslations("web.sell");
  const skins = useTranslations("web.skins");
  // The market's short chip labels where there are some (П-пулемёты, Тяжёлое).
  const label = (c: string) =>
    skins.has(`chipLabel.${c}`) ? skins(`chipLabel.${c}`) : skins(`category.${c}`);
  return (
    <div className="flex flex-col gap-3">
      <div className="bg-surface flex flex-col gap-2 rounded-xl p-3 sm:flex-row">
        <label className="relative flex-1">
          <Search
            className="text-fg-dim absolute left-3 top-1/2 size-4 -translate-y-1/2"
            aria-hidden
          />
          <input
            value={p.query}
            onChange={(e) => {
              p.onQuery(e.target.value);
            }}
            placeholder={t("search")}
            className={cn(inputClass, "pl-9")}
          />
        </label>
        <div className="flex min-w-0 gap-2">
          <select
            aria-label={t("sortLabel")}
            value={p.sort}
            onChange={(e) => {
              p.onSort(e.target.value as SellSort); // one of the three options below
            }}
            className={cn(selectClass, "min-w-0 flex-1 sm:w-48 sm:flex-none")}
          >
            {(["expensive", "cheap", "name"] as const).map((s) => (
              <option key={s} value={s}>
                {t(`sort.${s}`)}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={p.onToggleAll}
            className="bg-surface-2 hover:bg-border-strong flex shrink-0 items-center gap-2 rounded-lg px-3 text-sm font-medium"
          >
            {p.allChosen ? (
              <X className="size-4" aria-hidden />
            ) : (
              <CheckCheck className="size-4" aria-hidden />
            )}
            {p.allChosen ? t("clearAll") : t("selectAll")}
          </button>
          <button
            type="button"
            aria-label={t("refresh")}
            title={t("refresh")}
            className="bg-surface-2 hover:bg-border-strong grid size-10 shrink-0 place-items-center rounded-lg"
          >
            <RefreshCw className="size-4" aria-hidden />
          </button>
        </div>
      </div>
      {p.categories.length > 1 ? (
        <div className="flex gap-2 overflow-x-auto pb-1 [scrollbar-width:none]">
          <Chip
            active={p.category === null}
            onClick={() => {
              p.onCategory(null);
            }}
          >
            {t("all")}
          </Chip>
          {p.categories.map((c) => (
            <Chip
              key={c}
              active={p.category === c}
              onClick={() => {
                p.onCategory(c);
              }}
            >
              {label(c)}
            </Chip>
          ))}
        </div>
      ) : null}
    </div>
  );
}
