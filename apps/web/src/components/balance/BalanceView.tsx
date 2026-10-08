"use client";

import { buttonVariants } from "@csmarket/ui";
import { formatUzs } from "@csmarket/utils";
import { useQuery } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useTranslations } from "next-intl";

import { EntriesList } from "./EntriesList";

import { HistoryFilter } from "@/components/account/HistoryFilter";
import { Link } from "@/i18n/navigation";
import { useAuth } from "@/lib/auth";
import { BALANCE_KEY, getBalance } from "@/lib/balance";
import { DEPOSIT, TRANSACTIONS } from "@/lib/paths";
import { getPendingSales, PENDING_KEY } from "@/lib/sales";

export type TransactionsType = "all" | "topup" | "withdrawal";

interface BalanceViewProps {
  locale: string;
  /** The history filter (`?type=` on «Транзакции»). */
  type: TransactionsType;
}

/** «Транзакции»: the balance (with the way to top it up) and the filtered history; auth states as on
 * the account page. */
export function BalanceView({ locale, type }: BalanceViewProps) {
  const t = useTranslations("web.balance");
  const auth = useTranslations("web.auth");
  const nav = useTranslations("web.nav");
  const tx = useTranslations("web.transactions");
  const dep = useTranslations("web.deposit");
  const { status, user, signInHref } = useAuth();
  const signedIn = status === "signed_in" && user !== null;
  const balance = useQuery({
    queryKey: BALANCE_KEY,
    queryFn: getBalance,
    enabled: signedIn,
  });
  const pending = useQuery({ queryKey: PENDING_KEY, queryFn: getPendingSales, enabled: signedIn });
  if (status === "loading") {
    return <div aria-busy className="bg-surface h-40 animate-pulse rounded-lg" />;
  }
  if (status === "suspended") {
    return <p className="text-danger">{auth("suspended")}</p>;
  }
  if (!signedIn) {
    return (
      <div className="flex flex-col items-start gap-4">
        <p className="text-fg-muted">{t("signedOut")}</p>
        <a
          href={signInHref(locale)}
          className="bg-accent text-accent-fg rounded-md px-5 py-3 font-semibold"
        >
          {nav("signIn")}
        </a>
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-6">
      <div className="bg-surface flex flex-wrap items-center justify-between gap-4 rounded-xl p-5">
        <div>
          <p className="text-fg-muted text-sm">{t("amount")}</p>
          {balance.data ? (
            <p className="mt-1 text-3xl font-bold tabular-nums">
              {formatUzs(locale, balance.data.balance_uzs)}
            </p>
          ) : balance.isError ? (
            <p className="text-fg-dim mt-1 text-3xl font-bold">—</p>
          ) : (
            <div aria-busy className="bg-surface-2 mt-2 h-9 w-40 animate-pulse rounded-md" />
          )}
          {pending.data && Number(pending.data.pending_uzs) > 0 ? (
            <p className="text-fg-dim mt-1 text-sm">
              {t("pending", { sum: formatUzs(locale, pending.data.pending_uzs) })}
            </p>
          ) : null}
        </div>
        <Link href={DEPOSIT} className={buttonVariants({ size: "lg" })}>
          <Plus className="size-4" strokeWidth={3} aria-hidden />
          {dep("topUp")}
        </Link>
      </div>
      <div className="flex flex-col gap-3">
        <HistoryFilter
          current={type}
          options={[
            { key: "all", label: tx("all"), href: TRANSACTIONS },
            { key: "topup", label: tx("topups"), href: `${TRANSACTIONS}?type=topup` },
            {
              key: "withdrawal",
              label: tx("withdrawals"),
              href: `${TRANSACTIONS}?type=withdrawal`,
            },
          ]}
        />
        <EntriesList locale={locale} {...(type !== "all" ? { type } : {})} />
      </div>
    </div>
  );
}
