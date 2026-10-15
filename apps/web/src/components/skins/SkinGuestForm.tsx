"use client";

import { Button } from "@csmarket/ui";
import { formatUzs } from "@csmarket/utils";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { ChargeLines } from "./ChargeLines";
import { offeredKassas, PaymentPicker } from "./PaymentPicker";
import { PROVIDERS_KEY } from "./usePayMethods";

import type { SkinListing } from "@csmarket/utils/skins";

import { SignInDialog } from "@/components/auth/SignInDialog";
import { getProviders } from "@/lib/balance";
import { kassaCharge } from "@/lib/kassa-fee";

interface SkinGuestFormProps {
  locale: string;
  /** The selected offer. */
  offer: SkinListing;
}

/**
 * The buy form as a visitor sees it: the kassas, the total with the kassa's fee and the buy
 * button, as for a signed-in buyer, so the price is never hidden behind a sign-in. The button
 * opens the Steam sign-in; nothing is ordered. No balance tile: a visitor has none to read.
 */
export function SkinGuestForm({ locale, offer }: SkinGuestFormProps) {
  const t = useTranslations("web.buy");
  const providers = useQuery({ queryKey: PROVIDERS_KEY, queryFn: getProviders, staleTime: 60_000 });
  const kassas = providers.isError ? [] : providers.data;
  const [method, setMethod] = useState<string | null>(null);
  const [asking, setAsking] = useState(false);
  const offered = offeredKassas(kassas);
  const chosen = offered.find((p) => p.slug === method)?.slug ?? offered[0]?.slug ?? null;
  const price = offer.price_uzs;
  const charge = price !== null ? kassaCharge(Number(price), kassas, chosen) : null;

  return (
    <div className="flex flex-col gap-4">
      <PaymentPicker
        locale={locale}
        providers={kassas}
        method={chosen}
        onPick={setMethod}
        labels={{ legend: t("methodTitle"), test: t("methodTest"), none: t("methodNone") }}
      />
      {price !== null && (
        <ChargeLines locale={locale} base={Number(price)} charge={charge} kind="order" />
      )}
      <Button
        type="button"
        size="lg"
        onClick={() => {
          setAsking(true);
        }}
      >
        {price !== null
          ? t("pay", { price: formatUzs(locale, charge?.total ?? price) })
          : t("title")}
      </Button>
      <SignInDialog
        open={asking}
        onClose={() => {
          setAsking(false);
        }}
        locale={locale}
      />
    </div>
  );
}
