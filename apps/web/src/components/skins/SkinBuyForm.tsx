"use client";

import { Button } from "@csmarket/ui";
import { formatUzs } from "@csmarket/utils";
import { useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useRef, useState, useTransition } from "react";

import { PaymentPicker } from "./PaymentPicker";
import { useSelectedOffer, useSkinOffers } from "./SkinOffers";
import { usePayMethods } from "./usePayMethods";

import type { TradeLinkGate } from "./useTradeLinkGate";
import type { Locale } from "@csmarket/i18n";
import type { SkinListing } from "@csmarket/utils/skins";

import { Link, useRouter } from "@/i18n/navigation";
import { BALANCE_KEY } from "@/lib/balance";
import { orderArrivalPath } from "@/lib/order-arrival";
import { mintOrderKey, mintPayKey, orderKeyFor, type OrderKey } from "@/lib/order-key";
import {
  BalanceTooLowError,
  createAndPay,
  OfferGoneError,
  PriceChangedError,
  TradeLinkError,
} from "@/lib/orders";
import { verdictMessage } from "@/lib/trade-link";

interface SkinBuyFormProps {
  slug: string;
  locale: Locale;
  /** The selected offer. */
  offer: SkinListing;
  gate: TradeLinkGate & { link: string };
  refreshMe: () => Promise<void>;
}

/** A notice about one offer under one method: shown only while both are still chosen. */
interface Notice {
  text: string;
  /** The offer it is about; `null` when it is about none (nothing left). */
  listingId: string | null;
  method: string | null;
}

const cheapestOf = (list: readonly SkinListing[]): SkinListing | null =>
  list.reduce<SkinListing | null>(
    (a, b) => (a === null || Number(b.price_usd) < Number(a.price_usd) ? b : a),
    null,
  );

/** The method picker, the verdict on the link and the button, for a buyer with a link. */
export function SkinBuyForm({ slug, locale, offer, gate, refreshMe }: SkinBuyFormProps) {
  const t = useTranslations("web.buy");
  const tl = useTranslations("web.account.tradeLink.status");
  const nav = useTranslations("web.nav");
  const router = useRouter();
  const qc = useQueryClient();
  const offers = useSkinOffers();
  const { select, reprice, drop } = useSelectedOffer();
  const price = offer.price_uzs;
  const { kassas, chosen, provider, wallet, balancePending, pick } = usePayMethods(locale, price);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  // `busy` disables the button from the next render; this blocks a click that lands first.
  const inFlight = useRef(false);
  const [navigating, startNavigation] = useTransition();
  // Sticky per (offer, link): a retry after a failure replays the order already opened.
  const orderKey = useRef<OrderKey | null>(null);

  const verdict = verdictMessage(gate.state);
  const linkBad = verdict?.tone === "bad";
  // A price or offer notice is about the offer and method it was given for: picking
  // another one of either makes it stale, so it is no longer shown.
  const shown =
    notice !== null &&
    (notice.listingId === null || notice.listingId === offer.listing_id) &&
    notice.method === chosen
      ? notice.text
      : null;
  const say = (text: string, listingId: string | null): void => {
    setNotice({ text, listingId, method: chosen });
  };

  function onFailure(err: unknown, bought: SkinListing): void {
    if (err instanceof PriceChangedError) {
      // Pinned: at its new price it may no longer be the cheapest default.
      select(bought.listing_id);
      reprice(bought.listing_id, err.priceUzs);
      say(t("priceChanged", { price: formatUzs(locale, err.priceUzs) }), bought.listing_id);
    } else if (err instanceof OfferGoneError) {
      const rest = (offers ?? []).filter((o) => o.listing_id !== bought.listing_id);
      const hinted = err.nextOffer;
      drop(bought.listing_id);
      const next = rest.find((o) => o.listing_id === hinted?.listing_id) ?? cheapestOf(rest);
      if (next === null) {
        say(t("noneLeft"), null);
        return;
      }
      const nextPrice = next.listing_id === hinted?.listing_id ? hinted.price_uzs : next.price_uzs;
      if (nextPrice !== next.price_uzs && nextPrice !== null) reprice(next.listing_id, nextPrice);
      select(next.listing_id);
      say(
        t("offerGone", {
          price: nextPrice !== null ? formatUzs(locale, nextPrice) : `$${next.price_usd}`,
        }),
        next.listing_id,
      );
    } else if (err instanceof TradeLinkError) {
      if (err.code === "trade_link_bad") gate.refuse({ verdict: "bad", reason: err.reason });
      void refreshMe();
    } else if (err instanceof BalanceTooLowError) {
      // The tile turns red with what is missing once the balance is read again.
      void qc.invalidateQueries({ queryKey: BALANCE_KEY });
    } else {
      setFailed(true);
    }
  }

  async function buy(): Promise<void> {
    if (
      inFlight.current ||
      provider === null ||
      price === null ||
      linkBad ||
      gate.checking ||
      balancePending
    ) {
      return;
    }
    inFlight.current = true;
    setBusy(true);
    setNotice(null);
    setFailed(false);
    const bought = offer;
    const body = { slug, listing_id: bought.listing_id, price_uzs: Number(price) };
    const pay = { provider, locale };
    let key = orderKeyFor(orderKey.current, bought.listing_id, gate.link, mintOrderKey);
    orderKey.current = key;
    try {
      let placed = await createAndPay(body, pay, key.key, mintPayKey);
      if (placed === null) {
        // The replayed order expired: same offer, a fresh order, once.
        key = { ...key, key: mintOrderKey() };
        orderKey.current = key;
        placed = await createAndPay(body, pay, key.key, mintPayKey);
      }
      if (placed === null) throw new Error("order expired twice");
      orderKey.current = null;
      void qc.invalidateQueries({ queryKey: BALANCE_KEY });
      // A kassa is opened by the order page (once), so the bank app leaves it behind.
      const href = orderArrivalPath(placed.number, placed.opened ? provider : null);
      startNavigation(() => {
        router.push(href);
      });
    } catch (err) {
      onFailure(err, bought);
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      {gate.checking && <p className="text-fg-muted text-sm">{t("checkingLink")}</p>}
      {!gate.checking && verdict?.tone === "bad" && (
        <p className="text-danger text-sm">
          {tl(verdict.key)}{" "}
          <Link href="/account" className="underline">
            {nav("account")}
          </Link>
        </p>
      )}
      <PaymentPicker
        providers={kassas}
        method={chosen}
        onPick={pick}
        labels={{ legend: t("methodTitle"), test: t("methodTest"), none: t("methodNone") }}
        {...(wallet ? { wallet } : {})}
      />
      {shown !== null && (
        <p role="status" className="text-sm font-semibold text-amber-400">
          {shown}
        </p>
      )}
      {failed && (
        <p role="alert" className="text-danger text-sm">
          {t("failed")}
        </p>
      )}
      <Button
        type="button"
        size="lg"
        disabled={
          busy ||
          navigating ||
          gate.checking ||
          linkBad ||
          balancePending ||
          provider === null ||
          price === null
        }
        onClick={() => {
          void buy();
        }}
      >
        {price !== null ? t("pay", { price: formatUzs(locale, price) }) : t("title")}
      </Button>
    </div>
  );
}
