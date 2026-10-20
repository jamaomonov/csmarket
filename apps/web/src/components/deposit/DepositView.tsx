"use client";

import { DEFAULT_LOCALE, isLocale } from "@csmarket/i18n";
import { useQuery } from "@tanstack/react-query";
import { Wallet } from "lucide-react";
import { useTranslations } from "next-intl";

import { TopupForm } from "@/components/balance/TopupForm";
import { useAuth } from "@/lib/auth";
import { getProviders } from "@/lib/balance";

interface DepositViewProps {
  locale: string;
}

/** «Кошелёк»: top up through a kassa (withdrawals are hidden until they exist, owner 2026-10-20). */
export function DepositView({ locale }: DepositViewProps) {
  const t = useTranslations("web.deposit");
  const auth = useTranslations("web.auth");
  const nav = useTranslations("web.nav");
  const { status, user, signInHref } = useAuth();
  const signedIn = status === "signed_in" && user !== null;
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
  } else {
    body = (
      <TopupForm
        locale={isLocale(locale) ? locale : DEFAULT_LOCALE}
        // A failed list reads as "nothing open": the form says so instead of spinning.
        providers={providers.isError ? [] : providers.data}
      />
    );
  }

  return (
    <div className="flex flex-col gap-5">
      <h1 className="text-h2 flex items-center gap-3 font-semibold tracking-tight">
        <Wallet className="text-accent size-8" aria-hidden />
        {t("wallet")}
      </h1>
      {body}
    </div>
  );
}
