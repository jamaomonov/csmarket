"use client";

import { Chip, inputClass, cn } from "@csmarket/ui";
import {
  ArrowDownAZ,
  ArrowDownWideNarrow,
  ArrowUpNarrowWide,
  CheckCheck,
  RefreshCw,
  Search,
  X,
} from "lucide-react";
import { useTranslations } from "next-intl";

import { SortMenu } from "@/components/SortMenu";

export type SellSort = "expensive" | "cheap" | "name";

const SELL_SORTS = ["expensive", "cheap", "name"] as const satisfies readonly SellSort[];
const SORT_ICONS = {
  expensive: ArrowDownWideNarrow,
  cheap: ArrowUpNarrowWide,
  name: ArrowDownAZ,
} as const;

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
  onRefresh: () => void;
  refreshing: boolean;
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
      <div className="flex flex-col gap-2 sm:flex-row">
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
          <SortMenu
            label={t("sortLabel")}
            options={SELL_SORTS.map((s) => ({
              value: s,
              label: t(`sort.${s}`),
              icon: SORT_ICONS[s],
            }))}
            value={p.sort}
            onPick={p.onSort}
            className="min-w-0 flex-1 sm:w-52 sm:flex-none"
          />
          <button
            type="button"
            onClick={p.onToggleAll}
            className="border-border-strong bg-surface hover:bg-surface-hover flex h-10 shrink-0 items-center gap-2 rounded-lg border px-3 text-sm font-medium transition-colors"
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
            onClick={p.onRefresh}
            disabled={p.refreshing}
            className="border-border-strong bg-surface hover:bg-surface-hover grid size-10 shrink-0 place-items-center rounded-lg border transition-colors disabled:opacity-60"
          >
            <RefreshCw className={cn("size-4", p.refreshing && "animate-spin")} aria-hidden />
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
