"use client";

import { buttonVariants } from "@csmarket/ui";
import { assertNever } from "@csmarket/utils";
import { CheckCircle2, ExternalLink, Loader2, SearchCheck, Wallet } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useId, useState, type ReactNode } from "react";

import type { SkinTradeOut, TradeReason } from "@/lib/orders";

import { Link } from "@/i18n/navigation";
import { TRANSACTIONS } from "@/lib/paths";

/** Re-render once a minute while `active`, so time-bound lines stay true. */
function useMinuteTick(active: boolean): void {
  const [, setTick] = useState(0);
  useEffect(() => {
    if (!active) return;
    const id = setInterval(() => {
      setTick((n) => n + 1);
    }, 60_000);
    return () => {
      clearInterval(id);
    };
  }, [active]);
}

interface SkinTradeCardProps {
  trade: SkinTradeOut;
  locale: string;
  /** The order's steps, shown under the title. */
  steps?: ReactNode;
}

/**
 * The Steam trade on the order page: buying → the offer (open it in Steam, from whom,
 * accept by when) → received; or, failed, where the
 * money went. A purchase we are checking (`reason_code: "support"`) says so whatever its
 * state — under the offer when there is one to accept, instead of the state otherwise —
 * and a refund is mentioned only when `refunded_to` says it happened.
 */
export function SkinTradeCard({ trade, locale, steps = null }: SkinTradeCardProps) {
  const t = useTranslations("web.orders.trade");
  useMinuteTick(trade.state === "offer_sent");
  const review = trade.reason_code === "support";
  const refunded = trade.refunded_to === "balance";
  // An offer the buyer can still accept is never hidden, even while we check the purchase.
  const actionable = trade.state === "offer_sent" && trade.offer_url !== null;
  const titleId = useId();

  return (
    <section
      aria-labelledby={titleId}
      className="bg-surface flex w-full flex-col gap-4 rounded-xl p-5"
    >
      <h2 id={titleId} className="text-fg-dim text-xs font-semibold uppercase tracking-wider">
        {t("title")}
      </h2>
      {steps}
      {review && !actionable ? null : <TradeBody trade={trade} locale={locale} />}
      {review ? (
        <p className="flex items-center gap-2">
          <SearchCheck aria-hidden className="text-accent h-4 w-4 shrink-0" />
          {t("support")}
        </p>
      ) : null}
      {refunded ? (
        <Refunded reason={review ? null : trade.reason_code} />
      ) : trade.state === "failed" && !review ? (
        // Failed with no refund on record: nothing is promised.
        <p>{t("support")}</p>
      ) : null}
    </section>
  );
}

function TradeBody({ trade, locale }: SkinTradeCardProps) {
  const t = useTranslations("web.orders.trade");
  switch (trade.state) {
    case "buying":
      return (
        <p className="flex items-center gap-2">
          <Loader2 aria-hidden className="text-accent h-4 w-4 shrink-0 animate-spin" />
          {t("buying")}
        </p>
      );
    case "offer_sent":
      return <OfferSent trade={trade} locale={locale} />;
    case "accepted":
    case "released":
      return (
        <p className="text-success flex items-center gap-2 font-semibold">
          <CheckCircle2 aria-hidden className="h-4 w-4" />
          {t("accepted")}
        </p>
      );
    case "failed":
      // What failed means for the money is said beside it (`Refunded` / no promise).
      return null;
    default:
      return assertNever(trade.state);
  }
}

function OfferSent({ trade, locale }: SkinTradeCardProps) {
  const t = useTranslations("web.orders.trade");
  const seller = trade.seller?.name ? trade.seller : null;
  const until = trade.send_until;
  return (
    <div className="flex flex-col gap-3">
      <p className="font-semibold">{t("offer_sent")}</p>
      {seller ? (
        <p className="flex items-center gap-2 text-sm">
          <span className="text-fg-dim">{t("seller")}</span>
          {seller.avatar_url ? (
            // eslint-disable-next-line @next/next/no-img-element -- Steam CDN avatar, 20px; next/image adds nothing here
            <img
              src={seller.avatar_url}
              alt=""
              width={20}
              height={20}
              className="h-5 w-5 rounded-full"
            />
          ) : null}
          <span className="font-semibold">{seller.name}</span>
        </p>
      ) : null}
      {trade.offer_url ? (
        <a
          href={trade.offer_url}
          target="_blank"
          rel="noopener noreferrer"
          className={buttonVariants({ size: "lg", className: "self-start" })}
        >
          {t("openOffer")}
          <ExternalLink aria-hidden className="ml-2 h-4 w-4" />
        </a>
      ) : null}
      {until && Date.parse(until) > Date.now() ? (
        <p className="text-fg-dim text-sm">{t("acceptBy", { time: formatTime(locale, until) })}</p>
      ) : null}
    </div>
  );
}

interface RefundedProps {
  /** Why the trade failed (`null` while a purchase is checked); picks the line shown. */
  reason: TradeReason | null;
}

/** The money is back on the balance: why, in the buyer's terms, and a way to it. */
function Refunded({ reason }: RefundedProps) {
  const t = useTranslations("web.orders.trade");
  const line =
    reason === "try_later"
      ? "tryLater"
      : reason === "trade_link"
        ? "tradeLink"
        : reason === "sold_out"
          ? "soldOut"
          : "refunded";
  return (
    <div className="flex flex-col items-start gap-2">
      <p>{t(line)}</p>
      <Link
        href={TRANSACTIONS}
        className="text-accent inline-flex items-center gap-1.5 text-sm font-semibold"
      >
        <Wallet aria-hidden className="h-4 w-4" />
        {t("toBalance")}
      </Link>
    </div>
  );
}

function formatTime(locale: string, iso: string): string {
  return new Intl.DateTimeFormat(locale, { hour: "2-digit", minute: "2-digit" }).format(
    new Date(iso),
  );
}
