"use client";

import { Button } from "@csmarket/ui";
import { formatUzs } from "@csmarket/utils";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useRef, useState, useTransition } from "react";

import { offeredKassas, PaymentPicker, type WalletOption } from "./PaymentPicker";
import { useSelectedOffer, useSkinOffers } from "./SkinOffers";

import type { TradeLinkGate } from "./useTradeLinkGate";
import type { Locale } from "@csmarket/i18n";
import type { SkinListing } from "@csmarket/utils/skins";

import { Link, useRouter } from "@/i18n/navigation";
import { BALANCE_KEY, getBalance, getProviders } from "@/lib/balance";
import { mintOrderKey, mintPayKey, orderKeyFor, type OrderKey } from "@/lib/order-key";
import {
  BalanceTooLowError,
  createAndPay,
  isPayProvider,
  OfferGoneError,
  PriceChangedError,
  TradeLinkError,
  type PayProvider,
} from "@/lib/orders";
import { usePreferBalance, WALLET } from "@/lib/prefer-balance";
import { verdictMessage } from "@/lib/trade-link";

interface SkinBuyFormProps {
  slug: string;
  locale: Locale;
  /** The selected offer. */
  offer: SkinListing;
  gate: TradeLinkGate & { link: string };
  refreshMe: () => Promise<void>;
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
  const balance = useQuery({ queryKey: BALANCE_KEY, queryFn: getBalance });
  const providers = useQuery({
    queryKey: ["payments", "providers"],
    queryFn: getProviders,
    staleTime: 60_000,
  });
  const [method, setMethod] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  // `busy` disables the button from the next render; this blocks a click that lands first.
  const inFlight = useRef(false);
  const [navigating, startNavigation] = useTransition();
  // Sticky per (offer, link): a retry after a failure replays the order already opened.
  const orderKey = useRef<OrderKey | null>(null);

  // A failed list reads as "nothing open": the picker says so instead of spinning.
  const kassas = providers.isError ? [] : providers.data;
  const offered = offeredKassas(kassas);
  const price = offer.price_uzs;
  const funds = balance.data ? Number(balance.data.balance_uzs) : null;
  const covers = funds !== null && price !== null && funds >= Number(price);
  const markPicked = usePreferBalance(covers, setMethod, offered[0]?.slug ?? "");
  const chosen =
    method === WALLET
      ? covers
        ? WALLET
        : null
      : (offered.find((p) => p.slug === method)?.slug ?? offered[0]?.slug ?? null);
  const provider: PayProvider | null = chosen !== null && isPayProvider(chosen) ? chosen : null;
  const verdict = verdictMessage(gate.state);
  const linkBad = verdict?.tone === "bad";

  const wallet: WalletOption | undefined = balance.isError
    ? undefined
    : {
        label: t("balance"),
        detail:
          funds === null
            ? null
            : covers || price === null
              ? formatUzs(locale, funds)
              : t("balanceShort", { amount: formatUzs(locale, Number(price) - funds) }),
        covers,
        ...(funds !== null && price !== null && !covers
          ? {
              action: (
                <Link
                  href="/account/balance"
                  className="text-accent shrink-0 text-sm font-semibold"
                >
                  {t("topUp")}
                </Link>
              ),
            }
          : {}),
      };

  function onFailure(err: unknown, bought: SkinListing): void {
    if (err instanceof PriceChangedError) {
      // Pinned: at its new price it may no longer be the cheapest default.
      select(bought.listing_id);
      reprice(bought.listing_id, err.priceUzs);
      setNotice(t("priceChanged", { price: formatUzs(locale, err.priceUzs) }));
    } else if (err instanceof OfferGoneError) {
      const rest = (offers ?? []).filter((o) => o.listing_id !== bought.listing_id);
      const hinted = err.nextOffer;
      drop(bought.listing_id);
      const next = rest.find((o) => o.listing_id === hinted?.listing_id) ?? cheapestOf(rest);
      if (next === null) {
        setNotice(t("noneLeft"));
        return;
      }
      const nextPrice = next.listing_id === hinted?.listing_id ? hinted.price_uzs : next.price_uzs;
      if (nextPrice !== next.price_uzs && nextPrice !== null) reprice(next.listing_id, nextPrice);
      select(next.listing_id);
      setNotice(
        t("offerGone", {
          price: nextPrice !== null ? formatUzs(locale, nextPrice) : `$${next.price_usd}`,
        }),
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
    if (inFlight.current || provider === null || price === null || linkBad || gate.checking) {
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
      const go = placed.opened && provider !== WALLET ? "?go=1" : "";
      const href = `/orders/${encodeURIComponent(placed.number)}${go}`;
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
        onPick={(slug) => {
          markPicked();
          setMethod(slug);
        }}
        labels={{ legend: t("methodTitle"), test: t("methodTest"), none: t("methodNone") }}
        {...(wallet ? { wallet } : {})}
      />
      {notice && (
        <p role="status" className="text-sm font-semibold text-amber-400">
          {notice}
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
          busy || navigating || gate.checking || linkBad || provider === null || price === null
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
