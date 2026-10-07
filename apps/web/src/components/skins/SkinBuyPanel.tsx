"use client";

import { DEFAULT_LOCALE, isLocale } from "@csmarket/i18n";
import { cn } from "@csmarket/ui";
import { useTranslations } from "next-intl";
import { useId, type ReactNode } from "react";

import { SkinBuyForm } from "./SkinBuyForm";
import { useSelectedOffer, useSkinOffers } from "./SkinOffers";
import { useTradeLinkGate } from "./useTradeLinkGate";

import { SteamIcon } from "@/components/icons/SteamIcon";
import { Link } from "@/i18n/navigation";
import { useAuth } from "@/lib/auth";
import { displayPrice } from "@/lib/skins";

interface SkinBuyPanelProps {
  slug: string;
  locale: string;
}

const CTA = "bg-accent text-accent-fg inline-block rounded-md px-5 py-3 text-center font-semibold";

/**
 * Buy the selected offer (the cheapest until the buyer picks another in the list): sign in,
 * a trade link the skin can reach, a payment method, one button that says what it charges.
 * A moved price or a sold offer is shown, never charged silently.
 */
export function SkinBuyPanel({ slug, locale }: SkinBuyPanelProps) {
  const t = useTranslations("web.buy");
  const tauth = useTranslations("web.auth");
  const { status, user, signInHref, refreshMe } = useAuth();
  const signedIn = status === "signed_in" && user !== null;
  const gate = useTradeLinkGate(signedIn ? user : null, refreshMe);
  const offers = useSkinOffers();
  const { selected } = useSelectedOffer();
  const headingId = useId();

  let body: ReactNode;
  if (status === "loading" || offers === null) {
    body = <div aria-busy className="bg-surface-2 h-24 animate-pulse rounded-lg" />;
  } else if (selected === null) {
    body = <p className="text-fg-muted text-sm">{t("noneLeft")}</p>;
  } else if (status === "suspended") {
    body = <p className="text-danger text-sm">{tauth("suspended")}</p>;
  } else if (!signedIn) {
    body = (
      <a
        href={signInHref(locale)}
        className={cn(CTA, "inline-flex items-center justify-center gap-2")}
      >
        <SteamIcon className="size-5" aria-hidden />
        {t("signIn")}
      </a>
    );
  } else if (gate.link === null) {
    body = (
      <div className="flex flex-col items-start gap-3">
        <p className="text-fg-muted text-sm">{t("needLink")}</p>
        <Link href="/account" className={CTA}>
          {t("addLink")}
        </Link>
      </div>
    );
  } else {
    body = (
      <SkinBuyForm
        slug={slug}
        locale={isLocale(locale) ? locale : DEFAULT_LOCALE}
        offer={selected}
        gate={{ ...gate, link: gate.link }}
        refreshMe={refreshMe}
      />
    );
  }

  return (
    <section
      id="buy"
      aria-labelledby={headingId}
      className="border-border bg-surface-2/40 flex flex-col gap-4 rounded-xl border p-4"
    >
      <h2 id={headingId} className="text-[15px] font-bold">
        {t("title")}
      </h2>
      {selected && (
        <p className="flex items-baseline justify-between gap-3 text-sm">
          <span className="text-fg-muted">
            {t("offer")}
            {selected.float_value !== null && (
              <span className="text-fg-dim ml-2 tabular-nums">
                {selected.float_value.toFixed(4)}
              </span>
            )}
          </span>
          <span className="font-bold tabular-nums">
            {displayPrice(locale, selected.price_uzs, selected.price_usd)}
          </span>
        </p>
      )}
      {body}
      <p className="text-fg-dim text-[13px]">{t("howItWorks")}</p>
    </section>
  );
}
