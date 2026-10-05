"use client";

import { cn } from "@csmarket/ui";
import { useTranslations } from "next-intl";

import { OrdersList } from "@/components/account/OrdersList";
import { EntriesList } from "@/components/balance/EntriesList";
import { Link } from "@/i18n/navigation";
import { useAuth } from "@/lib/auth";
import { TRANSACTIONS } from "@/lib/paths";

export type TransactionsTab = "purchases" | "balance";

interface TransactionsViewProps {
  locale: string;
  tab: TransactionsTab;
}

const TABS: { key: TransactionsTab; href: string }[] = [
  { key: "purchases", href: TRANSACTIONS },
  { key: "balance", href: `${TRANSACTIONS}?tab=balance` },
];

/** «Транзакции»: the purchases and the balance history, one tab each (links, so shareable). */
export function TransactionsView({ locale, tab }: TransactionsViewProps) {
  const t = useTranslations("web.transactions");
  const nav = useTranslations("web.nav");
  const { status, user, signInHref } = useAuth();
  const signedIn = status === "signed_in" && user !== null;
  return (
    <div className="flex flex-col gap-5">
      <div className="bg-surface flex w-fit gap-1 rounded-lg p-1">
        {TABS.map((x) => (
          <Link
            key={x.key}
            href={x.href}
            aria-current={x.key === tab ? "page" : undefined}
            className={cn(
              "rounded-md px-4 py-2 text-[14px] font-medium transition-colors",
              x.key === tab ? "bg-surface-2 text-fg" : "text-fg-muted hover:text-fg",
            )}
          >
            {t(x.key)}
          </Link>
        ))}
      </div>
      {tab === "purchases" ? (
        // OrdersList asks a visitor to sign in itself.
        <OrdersList locale={locale} />
      ) : signedIn ? (
        <EntriesList locale={locale} />
      ) : status === "loading" ? (
        <div aria-busy className="bg-surface h-24 animate-pulse rounded-md" />
      ) : (
        <a
          href={signInHref(locale)}
          className="bg-accent text-accent-fg w-fit rounded-md px-5 py-3 font-semibold"
        >
          {nav("signIn")}
        </a>
      )}
    </div>
  );
}
