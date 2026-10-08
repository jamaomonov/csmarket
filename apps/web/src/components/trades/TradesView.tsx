"use client";

import { useTranslations } from "next-intl";

import { HistoryFilter } from "@/components/account/HistoryFilter";
import { OrdersList } from "@/components/account/OrdersList";
import { SalesList } from "@/components/account/SalesList";
import { TRADES } from "@/lib/paths";

export type TradesType = "all" | "purchases" | "sales";

interface TradesViewProps {
  locale: string;
  type: TradesType;
}

/** «Обмены»: the buyer's orders and the seller's sales. */
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
      {/* Each list asks a visitor to sign in itself. */}
      {type === "purchases" ? <OrdersList locale={locale} /> : null}
      {type === "sales" ? <SalesList locale={locale} /> : null}
      {type === "all" ? (
        <>
          <OrdersList locale={locale} />
          <h2 className="mt-4 text-xl font-bold">{t("sales")}</h2>
          <SalesList locale={locale} />
        </>
      ) : null}
    </div>
  );
}
