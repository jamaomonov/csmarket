import { formatUzs } from "@csmarket/utils";
import { useTranslations } from "next-intl";

import { kassaLabel } from "./PaymentPicker";

import type { KassaCharge } from "@/lib/kassa-fee";

interface ChargeLinesProps {
  locale: string;
  /** The price of the order, or what reaches the balance on a top-up. */
  base: number;
  /** The chosen kassa's fee (`kassaCharge`); `null` renders nothing. */
  charge: KassaCharge | null;
  kind: "order" | "topup";
}

/**
 * «Цена / Комиссия Payme / Итого» (a top-up: «На баланс / … / К оплате») under the payment
 * tiles, while a kassa with a fee is chosen (spec 2026-10-14-kassa-fee).
 */
export function ChargeLines({ locale, base, charge, kind }: ChargeLinesProps) {
  const t = useTranslations("web.buy.charge");
  if (charge === null) return null;
  const rows: [string, number, boolean][] = [
    [kind === "order" ? t("price") : t("toBalance"), base, false],
    [t("fee", { kassa: kassaLabel(charge.slug, charge.slug) ?? charge.slug }), charge.fee, false],
    [kind === "order" ? t("total") : t("toPay"), charge.total, true],
  ];
  return (
    <dl className="flex flex-col gap-1.5 text-sm">
      {rows.map(([label, value, strong]) => (
        <div key={label} className="flex items-baseline gap-3">
          <dt className={strong ? "text-fg font-semibold" : "text-fg-muted"}>{label}</dt>
          <span aria-hidden className="border-border flex-1 border-b border-dashed" />
          <dd className={strong ? "text-accent num font-bold" : "text-fg num"}>
            {formatUzs(locale, value)}
          </dd>
        </div>
      ))}
    </dl>
  );
}
