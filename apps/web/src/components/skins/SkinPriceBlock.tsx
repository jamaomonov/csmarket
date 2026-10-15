"use client";

import { offerHeadline, steamDiscount } from "@csmarket/utils/skins";
import { ExternalLink } from "lucide-react";
import { useTranslations } from "next-intl";

import { useSkinOffers } from "./SkinOffers";

import { displayPrice } from "@/lib/skins";

/**
 * The headline price — the cheapest live offer once offers load, with how much cheaper than
 * Steam it is; the stored price as «от …» before that — and, on a line of its own, the
 * Steam market link for comparison. Buying lives in `SkinBuyPanel`.
 */
export function SkinPriceBlock({
  storedUzs,
  storedUsd,
  steamUsd = null,
  steamUrl,
  locale,
}: {
  storedUzs: string | null;
  storedUsd: string | null;
  /** Steam's market price, for "cheaper than Steam". */
  steamUsd?: string | null;
  steamUrl: string;
  locale: string;
}) {
  const t = useTranslations("web.skins");
  const offers = useSkinOffers();
  const head = offerHeadline(storedUzs, storedUsd, offers);
  const price = displayPrice(locale, head.uzs, head.usd);
  const off = head.usd !== null ? steamDiscount(head.usd, steamUsd) : null;
  return (
    <div className="space-y-2">
      <p className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="text-h1 font-sans font-semibold tracking-tight">
          {price === null ? t("soldOut") : head.from ? t("fromPrice", { price }) : price}
        </span>
        {off !== null && (
          <span className="bg-accent-subtle text-accent text-label rounded-sm px-2 py-0.5 font-semibold">
            {t("belowSteam", { percent: off })}
          </span>
        )}
      </p>
      <a
        href={steamUrl}
        target="_blank"
        rel="nofollow noopener noreferrer"
        className="text-fg-dim hover:text-fg text-small inline-flex items-center gap-1"
      >
        {t("steamPrice")}
        <ExternalLink className="h-3.5 w-3.5" aria-hidden />
      </a>
    </div>
  );
}
