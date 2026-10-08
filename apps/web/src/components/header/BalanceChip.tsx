"use client";

import { formatUzs } from "@csmarket/utils";
import { useQuery } from "@tanstack/react-query";
import { ChevronRight, Hourglass, Plus } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { Link } from "@/i18n/navigation";
import { BALANCE_KEY, getBalance } from "@/lib/balance";
import { DEPOSIT, TRADES } from "@/lib/paths";
import { getPendingSales, PENDING_KEY } from "@/lib/sales";

/**
 * The signed-in balance with a «+» to top up; `compact` drops the «сум» on phones. Under
 * it, money from sales still in Steam's 7 days, a link to those sales on «Обмены».
 */
export function BalanceChip({ compact = false }: { compact?: boolean }) {
  const t = useTranslations("web.nav");
  const locale = useLocale();
  const balance = useQuery({ queryKey: BALANCE_KEY, queryFn: getBalance });
  const amount = balance.data?.balance_uzs;
  const pending = useQuery({ queryKey: PENDING_KEY, queryFn: getPendingSales });
  const hold = pending.data?.pending_uzs;
  return (
    <span className="bg-surface flex items-center gap-2.5 rounded-lg py-1.5 pl-3.5 pr-1.5 text-[14px] font-semibold">
      <span className="flex flex-col leading-tight">
        <span className="num">
          {amount === undefined
            ? "…"
            : compact
              ? formatUzs(locale, amount).replace(/\s\D+$/, "")
              : formatUzs(locale, amount)}
        </span>
        {hold !== undefined && Number(hold) > 0 ? (
          <Link
            href={`${TRADES}?type=hold`}
            data-testid="balance-hold"
            aria-label={t("inHold", { sum: formatUzs(locale, hold) })}
            className="text-warning num flex items-center gap-0.5 whitespace-nowrap text-[11px] font-medium hover:underline"
          >
            {compact ? (
              // Phones: no room for words — an hourglass and the sum.
              <>
                <Hourglass aria-hidden className="size-3" strokeWidth={2.5} />+
                {formatUzs(locale, hold).replace(/\s\D+$/, "")}
              </>
            ) : (
              t("inHold", { sum: formatUzs(locale, hold) })
            )}
            <ChevronRight aria-hidden className="size-3" strokeWidth={2.5} />
          </Link>
        ) : null}
      </span>
      <Link
        href={DEPOSIT}
        aria-label={t("topUp")}
        className="bg-accent text-accent-fg hover:bg-accent-hover focus-visible:ring-accent focus-visible:ring-offset-bg flex size-7 items-center justify-center rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2"
      >
        <Plus className="size-4" strokeWidth={3} aria-hidden />
      </Link>
    </span>
  );
}
