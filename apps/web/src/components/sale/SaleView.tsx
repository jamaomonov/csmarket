"use client";

import { SessionApiError } from "@csmarket/api-client";
import { buttonVariants } from "@csmarket/ui";
import { assertNever, formatUzs } from "@csmarket/utils";
import { useQuery } from "@tanstack/react-query";
import { Check, Hourglass, Loader2, X } from "lucide-react";
import { useTranslations } from "next-intl";

import { CARD_BRANDS } from "@/components/sell/PayoutPicker";
import { ItemThumb } from "@/components/trades/ItemThumb";
import { StatusBadge } from "@/components/trades/StatusBadge";
import { TradeSteps, type TradeStep } from "@/components/trades/TradeSteps";
import { Link } from "@/i18n/navigation";
import { useAuth } from "@/lib/auth";
import { TRADES } from "@/lib/paths";
import { getSale, saleKey, salePollInterval, type SaleOut } from "@/lib/sales";
import { saleBadge, shortDay, type Tone } from "@/lib/trade-status";

interface SaleViewProps {
  locale: string;
  number: string;
}

const notFound = (err: unknown): boolean => err instanceof SessionApiError && err.status === 404;

/** What the sale's state means to the seller: a headline and one sentence. */
function useStateText(sale: SaleOut, locale: string): { title: string; text: string } {
  const t = useTranslations("web.sales.state");
  const amount = formatUzs(locale, sale.payout_uzs);
  const card = sale.card ? `${CARD_BRANDS[sale.card.type]} •••• ${sale.card.last4}` : "";
  const when = (iso: string | null) =>
    iso
      ? new Intl.DateTimeFormat(locale, { day: "numeric", month: "long" }).format(new Date(iso))
      : "";
  switch (sale.status) {
    case "creating":
      return { title: t("creating.title"), text: t("creating.text") };
    case "offered":
      if (!sale.offer) return { title: t("offered.title"), text: t("offered.textNoOffer") };
      return {
        title: t("offered.title"),
        text: t("offered.text", {
          bot: sale.offer.bot_name ?? "",
          time: sale.offer.expires_at
            ? new Intl.DateTimeFormat(locale, { timeStyle: "short", dateStyle: "short" }).format(
                new Date(sale.offer.expires_at),
              )
            : "",
        }),
      };
    case "hold":
      return {
        title: t("hold.title"),
        text: t("hold.text", { amount, date: when(sale.money_at) }),
      };
    case "credited":
      return { title: t("credited.title"), text: t("credited.text", { amount }) };
    case "payout":
      if (sale.payout_status === "paid")
        return { title: t("paid.title"), text: t("paid.text", { amount, card }) };
      if (sale.payout_status === "canceled")
        return { title: t("closed.title"), text: t("closed.text") };
      if (sale.payout_status === "waiting_hold") {
        return {
          title: t("hold.title"),
          text: t("hold.text", { amount, date: when(sale.money_at) }),
        };
      }
      if (sale.payout_status === "rejected") {
        const refunded = formatUzs(locale, sale.items_uzs);
        return {
          title: t("rejected.title"),
          text: sale.payout_reject_reason
            ? t("rejected.text", { amount: refunded, reason: sale.payout_reject_reason })
            : t("rejected.textPlain", { amount: refunded }),
        };
      }
      return { title: t("payout.title"), text: t("payout.text", { amount, card }) };
    case "closed":
      return { title: t("closed.title"), text: t("closed.text") };
    case "reverted":
      return { title: t("reverted.title"), text: t("reverted.text") };
    default:
      return assertNever(sale.status);
  }
}

/** Trade accepted → Steam's 7 days → the money on the balance or the card. */
function useSaleSteps(sale: SaleOut, locale: string): TradeStep[] | null {
  const t = useTranslations("web.trades.steps");
  const paid = sale.payout_status;
  if (sale.status === "closed" || sale.status === "reverted" || paid === "canceled") return null;
  const money = t(sale.payout_to === "card" && paid !== "rejected" ? "card" : "balance");
  const due = sale.money_at ? shortDay(locale, sale.money_at) : null;
  const waiting = sale.status === "hold" || paid === "waiting_hold";
  const done = sale.status === "credited" || paid === "paid" || paid === "rejected";
  const accepted = waiting || done || sale.status === "payout";
  return [
    { label: t("accepted"), state: accepted ? "done" : "now" },
    {
      label: t("protection"),
      note: t("days7"),
      state: waiting ? "now" : accepted ? "done" : "todo",
    },
    { label: money, note: due, state: done ? "done" : accepted && !waiting ? "now" : "todo" },
  ];
}

const ICONS: Record<Tone, typeof Check> = {
  ok: Check,
  wait: Hourglass,
  run: Loader2,
  bad: X,
  muted: X,
};

const ICON_TONES: Record<Tone, string> = {
  ok: "bg-success/15 text-success",
  wait: "bg-warning/15 text-warning",
  run: "bg-info/15 text-info",
  bad: "bg-danger/15 text-danger",
  muted: "bg-surface-2 text-fg-dim",
};

function SaleBody({ sale, locale }: { sale: SaleOut; locale: string }) {
  const t = useTranslations("web.sales");
  const sell = useTranslations("web.sell");
  const skins = useTranslations("web.skins");
  const state = useStateText(sale, locale);
  const steps = useSaleSteps(sale, locale);
  const tone = saleBadge(sale).tone;
  const Icon = ICONS[tone];
  const uzs = (v: string) => formatUzs(locale, v);
  return (
    <div className="flex flex-col gap-5">
      <section className="bg-surface flex flex-col gap-5 rounded-xl p-5" data-state={sale.status}>
        <div className="flex items-start gap-4">
          <span
            aria-hidden
            className={`flex size-10 shrink-0 items-center justify-center rounded-xl ${ICON_TONES[tone]}`}
          >
            <Icon className="size-5" />
          </span>
          <div className="flex flex-col items-start gap-1">
            <h2 className="text-lg font-bold">{state.title}</h2>
            <p className="text-fg-muted">{state.text}</p>
            {sale.offer ? (
              <a
                href={sale.offer.url}
                target="_blank"
                rel="noopener noreferrer"
                className={buttonVariants({ size: "lg", className: "mt-2" })}
              >
                {t("openOffer")}
              </a>
            ) : null}
          </div>
        </div>
        {steps ? <TradeSteps steps={steps} /> : null}
      </section>
      <div className="grid items-start gap-5 md:grid-cols-[1fr_300px]">
        <ul className="bg-surface flex flex-col rounded-xl px-4 py-1">
          {sale.items.map((i) => (
            <li
              key={i.asset_id}
              className="border-border flex items-center gap-3 border-b py-2.5 last:border-0"
            >
              <ItemThumb
                imageUrl={i.image_url}
                rarityColor={i.rarity_color}
                className="h-11 w-16"
              />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-medium">{i.name}</span>
                {i.exterior ? (
                  <span className="text-fg-dim block text-[12px]">
                    {skins(`exterior.${i.exterior}`)}
                  </span>
                ) : null}
              </span>
              <span className="num text-sm font-semibold">{uzs(i.price_uzs)}</span>
            </li>
          ))}
        </ul>
        <dl className="bg-surface grid grid-cols-[1fr_auto] gap-x-6 gap-y-2 rounded-xl p-5 text-sm">
          <dt className="text-fg-muted">{sell("summary.items")}</dt>
          <dd className="num text-right">{uzs(sale.items_uzs)}</dd>
          {sale.payout_to === "card" ? (
            <>
              <dt className="text-fg-muted">{t("fee")}</dt>
              <dd className="num text-right">−{uzs(sale.fee_uzs)}</dd>
            </>
          ) : (
            <>
              <dt className="text-fg-muted">{t("bonus")}</dt>
              <dd className="num text-accent text-right">+{uzs(sale.bonus_uzs)}</dd>
            </>
          )}
          <dt className="border-border border-t pt-2 font-bold">{sell("summary.payout")}</dt>
          <dd className="num text-accent border-border border-t pt-2 text-right font-bold">
            {uzs(sale.payout_uzs)}
          </dd>
        </dl>
      </div>
    </div>
  );
}

/** When the sale was made, and where the money goes. */
function SaleSubtitle({ sale, locale }: { sale: SaleOut; locale: string }) {
  const t = useTranslations("web.trades");
  const when = new Intl.DateTimeFormat(locale, {
    day: "numeric",
    month: "long",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(sale.created_at));
  const to = sale.card
    ? `${t("toCard")} ${CARD_BRANDS[sale.card.type]} •••• ${sale.card.last4}`
    : t("toBalance");
  return <p className="text-fg-dim text-sm">{`${when} · ${to}`}</p>;
}

/** A sale's page: what to do now (accept the offer), then the money's way, live. */
export function SaleView({ locale, number }: SaleViewProps) {
  const t = useTranslations("web.sales");
  const nav = useTranslations("web.nav");
  const { status, user, signInHref } = useAuth();
  const signedIn = status === "signed_in" && user !== null;
  const sale = useQuery({
    queryKey: saleKey(number),
    queryFn: () => getSale(number),
    enabled: signedIn,
    refetchInterval: (q) => salePollInterval(q.state.data),
  });
  let body;
  if (status === "loading" || (signedIn && sale.isPending)) {
    body = <div aria-busy className="bg-surface h-48 animate-pulse rounded-xl" />;
  } else if (!signedIn) {
    body = (
      <a href={signInHref(locale)} className={buttonVariants({ size: "lg" })}>
        {nav("signIn")}
      </a>
    );
  } else if (sale.isError || !sale.data) {
    body = (
      <p className="text-fg-muted">{notFound(sale.error) ? t("notFound") : t("loadFailed")}</p>
    );
  } else {
    body = <SaleBody sale={sale.data} locale={locale} />;
  }
  return (
    <div className="flex flex-col gap-5">
      <Link href={TRADES} className="text-fg-dim hover:text-fg text-sm">
        ← {t("back")}
      </Link>
      <header className="flex flex-col gap-1">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <h1 className="text-3xl font-bold">{t("number", { number })}</h1>
          {sale.data ? <StatusBadge badge={saleBadge(sale.data)} /> : null}
        </div>
        {sale.data ? <SaleSubtitle sale={sale.data} locale={locale} /> : null}
      </header>
      {body}
    </div>
  );
}
