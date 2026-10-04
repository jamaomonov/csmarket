"use client";

import { formatUzs } from "@csmarket/utils";
import { useQuery } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { Link } from "@/i18n/navigation";
import { BALANCE_KEY, getBalance } from "@/lib/balance";
import { BALANCE } from "@/lib/paths";

/** The signed-in balance with a «+» to top up; `compact` drops the «сум» on phones. */
export function BalanceChip({ compact = false }: { compact?: boolean }) {
  const t = useTranslations("web.nav");
  const locale = useLocale();
  const balance = useQuery({ queryKey: BALANCE_KEY, queryFn: getBalance });
  const amount = balance.data?.balance_uzs;
  return (
    <span className="bg-surface flex items-center gap-2.5 rounded-lg py-1.5 pl-3.5 pr-1.5 text-[14px] font-semibold">
      <span className="num">
        {amount === undefined
          ? "…"
          : compact
            ? formatUzs(locale, amount).replace(/\s\D+$/, "")
            : formatUzs(locale, amount)}
      </span>
      <Link
        href={BALANCE}
        aria-label={t("topUp")}
        className="bg-accent text-accent-fg hover:bg-accent-hover focus-visible:ring-accent focus-visible:ring-offset-bg flex size-7 items-center justify-center rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2"
      >
        <Plus className="size-4" strokeWidth={3} aria-hidden />
      </Link>
    </span>
  );
}
