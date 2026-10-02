"use client";

import { formatUzs } from "@csmarket/utils";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { offeredKassas, type WalletOption } from "./PaymentPicker";

import type { Provider } from "@/lib/balance";

import { Link } from "@/i18n/navigation";
import { BALANCE_KEY, getBalance, getProviders } from "@/lib/balance";
import { isPayProvider, type PayProvider } from "@/lib/orders";
import { BALANCE } from "@/lib/paths";
import { usePreferBalance, WALLET } from "@/lib/prefer-balance";

/** Query key of the kassas open now (anonymous, shared by every picker). */
export const PROVIDERS_KEY = ["payments", "providers"] as const;

export interface PayMethods {
  /** The kassas open now (`[]` when the list failed); `undefined` while it loads. */
  kassas: readonly Provider[] | undefined;
  /** The method shown selected: a kassa slug, `wallet`, or `null` for none. */
  chosen: string | null;
  /** `chosen` as the pay route takes it. */
  provider: PayProvider | null;
  /** The balance tile; absent when the balance could not be read. */
  wallet: WalletOption | undefined;
  /**
   * The balance is still loading: the method shown may still switch to it (it starts
   * selected once it covers the price), so nothing should be paid yet.
   */
  balancePending: boolean;
  /** A tap on a tile: the buyer's own choice, never switched for them. */
  pick: (method: string) => void;
}

/**
 * The balance and the kassas as payment methods for a price (the buy panel's and the
 * order page's picker). The balance starts selected when it covers the price — unless
 * the buyer already chose a method (`initial`, e.g. the kassa picked on the item page).
 */
export function usePayMethods(
  locale: string,
  price: string | null,
  initial: PayProvider | null = null,
): PayMethods {
  const t = useTranslations("web.buy");
  const balance = useQuery({ queryKey: BALANCE_KEY, queryFn: getBalance });
  const providers = useQuery({ queryKey: PROVIDERS_KEY, queryFn: getProviders, staleTime: 60_000 });
  const [method, setMethod] = useState<string>(initial ?? "");

  // A failed list reads as "nothing open": the picker says so instead of spinning.
  const kassas = providers.isError ? [] : providers.data;
  const offered = offeredKassas(kassas);
  const funds = balance.data ? Number(balance.data.balance_uzs) : null;
  const covers = funds !== null && price !== null && funds >= Number(price);
  const markPicked = usePreferBalance(
    covers && initial === null,
    setMethod,
    offered[0]?.slug ?? "",
  );
  const chosen =
    method === WALLET
      ? covers
        ? WALLET
        : null
      : (offered.find((p) => p.slug === method)?.slug ?? offered[0]?.slug ?? null);
  const provider = chosen !== null && isPayProvider(chosen) ? chosen : null;

  const wallet: WalletOption | undefined = balance.isError
    ? undefined
    : {
        label: t("balance"),
        detail:
          funds === null
            ? null
            : covers || price === null
              ? formatUzs(locale, funds)
              : t("balanceShort", { amount: formatUzs(locale, Number(price) - funds) }),
        covers,
        ...(funds !== null && price !== null && !covers
          ? {
              action: (
                <Link href={BALANCE} className="text-accent shrink-0 text-sm font-semibold">
                  {t("topUp")}
                </Link>
              ),
            }
          : {}),
      };

  return {
    kassas,
    chosen,
    provider,
    wallet,
    balancePending: balance.isPending,
    pick: (slug) => {
      markPicked();
      setMethod(slug);
    },
  };
}
