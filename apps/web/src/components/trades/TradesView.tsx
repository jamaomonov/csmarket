"use client";

import { useTranslations } from "next-intl";

import { HistoryFilter } from "@/components/account/HistoryFilter";
import { OrdersList } from "@/components/account/OrdersList";
import { TRADES } from "@/lib/paths";

export type TradesType = "all" | "purchases" | "sales";

interface TradesViewProps {
  locale: string;
  type: TradesType;
}

/** «Обмены»: the buyer's orders; sales join when selling opens (none yet). */
export function TradesView({ locale, type }: TradesViewProps) {
  const t = useTranslations("web.trades");
  return (
    <div className="flex flex-col gap-5">
      <HistoryFilter
        current={type}
        options={[
          { key: "all", label: t("all"), href: TRADES },
          { key: "purchases", label: t("purchases"), href: `${TRADES}?type=purchases` },
          { key: "sales", label: t("sales"), href: `${TRADES}?type=sales` },
        ]}
      />
      {type === "sales" ? (
        <p className="text-fg-muted">{t("salesEmpty")}</p>
      ) : (
        // OrdersList asks a visitor to sign in itself.
        <OrdersList locale={locale} />
      )}
    </div>
  );
}
