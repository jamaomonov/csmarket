/** Buying and selling side by side, each shown on real skins. */
import { getTranslations } from "next-intl/server";

import { BuyFlow } from "./BuyFlow";
import { SellFlow } from "./SellFlow";

import type { SkinItem } from "@csmarket/utils/skins";

interface Props {
  buyItem: SkinItem | null;
  sellItems: SkinItem[];
  locale: string;
}

export async function BuySell({ buyItem, sellItems, locale }: Props) {
  const t = await getTranslations({ locale, namespace: "web.landing" });
  return (
    <section aria-label={`${t("buyPanel.kicker")} · ${t("sellPanel.kicker")}`}>
      <div className="wrap duo">
        <BuyFlow item={buyItem} locale={locale} />
        <SellFlow items={sellItems} locale={locale} />
      </div>
    </section>
  );
}
