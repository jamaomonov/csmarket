"use client";

import { DEFAULT_LOCALE, isLocale } from "@csmarket/i18n";
import { formatUzs } from "@csmarket/utils";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { EntriesList } from "./EntriesList";
import { TopupForm } from "./TopupForm";

import { useAuth } from "@/lib/auth";
import { BALANCE_KEY, getBalance, getProviders } from "@/lib/balance";

interface BalanceViewProps {
  locale: string;
}

/** The balance page body; auth states as on the account page. */
export function BalanceView({ locale }: BalanceViewProps) {
  const t = useTranslations("web.balance");
  const auth = useTranslations("web.auth");
  const nav = useTranslations("web.nav");
  const { status, user, signInHref } = useAuth();
  const signedIn = status === "signed_in" && user !== null;
  const balance = useQuery({
    queryKey: BALANCE_KEY,
    queryFn: getBalance,
    enabled: signedIn,
  });
  const providers = useQuery({
    queryKey: ["payments", "providers"],
    queryFn: getProviders,
    enabled: signedIn,
    staleTime: 60_000,
  });

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
      <div className="bg-surface rounded-lg p-5">
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
      </div>
      <TopupForm
        locale={isLocale(locale) ? locale : DEFAULT_LOCALE}
        // A failed list reads as "nothing open": the form says so instead of spinning.
        providers={providers.isError ? [] : providers.data}
      />
      <EntriesList locale={locale} />
    </div>
  );
}
