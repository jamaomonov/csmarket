"use client";

import { useTranslations } from "next-intl";

interface SellStepsProps {
  /** Where the money goes: the third step's words and timing depend on it. */
  toCard: boolean;
}

/** What happens after «Продать»: accept the trade, Steam's 7 days, then the money. */
export function SellSteps({ toCard }: SellStepsProps) {
  const t = useTranslations("web.sell.steps");
  return (
    <div className="text-fg-dim text-xs">
      <p className="text-fg-muted mb-1 font-semibold">{t("title")}</p>
      <ol className="list-inside list-decimal space-y-0.5">
        <li>{t("accept")}</li>
        <li>{t("protection")}</li>
        <li>{t(toCard ? "card" : "balance")}</li>
      </ol>
    </div>
  );
}
