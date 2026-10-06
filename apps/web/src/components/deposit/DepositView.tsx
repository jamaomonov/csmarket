"use client";

import { DEFAULT_LOCALE, isLocale } from "@csmarket/i18n";
import { cn } from "@csmarket/ui";
import { useQuery } from "@tanstack/react-query";
import { ArrowDownToLine, ArrowUpFromLine, Wallet } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { TopupForm } from "@/components/balance/TopupForm";
import { useAuth } from "@/lib/auth";
import { getProviders } from "@/lib/balance";

type Tab = "topup" | "withdraw";

interface DepositViewProps {
  locale: string;
}

/** «Кошелёк»: top up through a kassa; withdrawals are on their way. */
export function DepositView({ locale }: DepositViewProps) {
  const t = useTranslations("web.deposit");
  const auth = useTranslations("web.auth");
  const nav = useTranslations("web.nav");
  const { status, user, signInHref } = useAuth();
  const signedIn = status === "signed_in" && user !== null;
  const [tab, setTab] = useState<Tab>("topup");
  const providers = useQuery({
    queryKey: ["payments", "providers"],
    queryFn: getProviders,
    enabled: signedIn,
    staleTime: 60_000,
  });

  let body;
  if (status === "loading") {
    body = <div aria-busy className="bg-surface h-80 animate-pulse rounded-xl" />;
  } else if (status === "suspended") {
    body = <p className="text-danger">{auth("suspended")}</p>;
  } else if (!signedIn) {
    body = (
      <a
        href={signInHref(locale)}
        className="bg-accent text-accent-fg w-fit rounded-md px-5 py-3 font-semibold"
      >
        {nav("signIn")}
      </a>
    );
  } else if (tab === "withdraw") {
    body = (
      <div className="bg-surface text-fg-muted flex items-center gap-3 rounded-xl p-6">
        <ArrowUpFromLine className="text-fg-dim size-5" aria-hidden />
        {t("withdrawSoon")}
      </div>
    );
  } else {
    body = (
      <TopupForm
        locale={isLocale(locale) ? locale : DEFAULT_LOCALE}
        // A failed list reads as "nothing open": the form says so instead of spinning.
        providers={providers.isError ? [] : providers.data}
      />
    );
  }

  const tabs: { key: Tab; icon: typeof Wallet }[] = [
    { key: "topup", icon: ArrowDownToLine },
    { key: "withdraw", icon: ArrowUpFromLine },
  ];
  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h1 className="flex items-center gap-3 text-3xl font-bold">
          <Wallet className="text-accent size-8" aria-hidden />
          {t("wallet")}
        </h1>
        {signedIn ? (
          <div role="tablist" className="bg-surface flex gap-1 rounded-lg p-1">
            {tabs.map(({ key, icon: Icon }) => (
              <button
                key={key}
                type="button"
                role="tab"
                aria-selected={tab === key}
                onClick={() => {
                  setTab(key);
                }}
                className={cn(
                  "flex items-center gap-2 rounded-md px-4 py-2 text-[14px] font-medium transition-colors",
                  tab === key ? "bg-surface-2 text-fg" : "text-fg-muted hover:text-fg",
                )}
              >
                <Icon className={cn("size-4", tab === key && "text-accent")} aria-hidden />
                {t(key)}
              </button>
            ))}
          </div>
        ) : null}
      </div>
      {body}
    </div>
  );
}
