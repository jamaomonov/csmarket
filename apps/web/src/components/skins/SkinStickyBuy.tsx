"use client";

import { Button } from "@csmarket/ui";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { useSelectedOffer } from "./SkinOffers";

import { displayPrice } from "@/lib/skins";

/** The buy panel's anchor (`SkinBuyPanel`). */
const BUY_ID = "buy";

/**
 * On a phone the buy panel sits below the picture and the wears: a bar at the bottom of the
 * screen keeps the selected offer's price and «Купить» in reach, and takes the buyer to the
 * panel. It hides while the panel is on screen; from `md` up the panel is beside the picture.
 */
export function SkinStickyBuy({ locale }: { locale: string }) {
  const t = useTranslations("web.buy");
  const { selected } = useSelectedOffer();
  const [panelInView, setPanelInView] = useState(false);

  useEffect(() => {
    const panel = document.getElementById(BUY_ID);
    if (panel === null || typeof IntersectionObserver === "undefined") return;
    const seen = new IntersectionObserver(([entry]) => {
      setPanelInView(entry?.isIntersecting ?? false);
    });
    seen.observe(panel);
    return () => {
      seen.disconnect();
    };
  }, []);

  if (selected === null) return null;
  return (
    <>
      {/* Room under the page's last line, so the bar never covers it. */}
      <div aria-hidden className="h-20 md:hidden" />
      <div
        data-testid="sticky-buy"
        hidden={panelInView}
        className="bg-surface-solid border-border fixed inset-x-0 bottom-0 z-30 flex items-center gap-3 border-t p-3 md:hidden"
      >
        <span className="num flex-1 text-lg font-bold">
          {displayPrice(locale, selected.price_uzs, selected.price_usd)}
        </span>
        <Button
          size="lg"
          onClick={() => {
            document
              .getElementById(BUY_ID)
              ?.scrollIntoView({ behavior: "smooth", block: "center" });
          }}
        >
          {t("title")}
        </Button>
      </div>
    </>
  );
}
