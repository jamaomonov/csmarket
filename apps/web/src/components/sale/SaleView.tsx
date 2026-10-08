"use client";

import { SessionApiError } from "@csmarket/api-client";
import { buttonVariants } from "@csmarket/ui";
import { assertNever, formatUzs } from "@csmarket/utils";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { CARD_BRANDS } from "@/components/sell/PayoutPicker";
import { Link } from "@/i18n/navigation";
import { useAuth } from "@/lib/auth";
import { TRADES } from "@/lib/paths";
import { getSale, saleKey, salePollInterval, type SaleOut } from "@/lib/sales";

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

function SaleBody({ sale, locale }: { sale: SaleOut; locale: string }) {
  const t = useTranslations("web.sales");
  const sell = useTranslations("web.sell");
  const state = useStateText(sale, locale);
  const uzs = (v: string) => formatUzs(locale, v);
  return (
    <div className="flex flex-col gap-6">
      <section
        className="bg-surface flex flex-col items-start gap-3 rounded-xl p-5"
        data-state={sale.status}
      >
        <h2 className="text-xl font-bold">{state.title}</h2>
        <p className="text-fg-muted">{state.text}</p>
        {sale.offer ? (
          <a
            href={sale.offer.url}
            target="_blank"
            rel="noopener noreferrer"
            className={buttonVariants({ size: "lg" })}
          >
            {t("openOffer")}
          </a>
        ) : null}
      </section>
      <ul className="flex flex-col gap-1.5">
        {sale.items.map((i) => (
          <li key={i.asset_id} className="bg-surface flex items-center gap-3 rounded-lg p-2">
            {i.image_url ? (
              // eslint-disable-next-line @next/next/no-img-element -- Steam CDN images
              <img src={i.image_url} alt="" className="h-8 w-12 shrink-0 object-contain" />
            ) : null}
            <span className="min-w-0 flex-1 truncate text-sm">{i.name}</span>
            <span className="num text-sm font-semibold">{uzs(i.price_uzs)}</span>
          </li>
        ))}
      </ul>
      <dl className="grid grid-cols-[1fr_auto] gap-x-6 gap-y-1 text-sm">
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
            <dd className="num text-right">+{uzs(sale.bonus_uzs)}</dd>
          </>
        )}
        <dt className="font-bold">{sell("summary.payout")}</dt>
        <dd className="num text-accent text-right font-bold">{uzs(sale.payout_uzs)}</dd>
      </dl>
    </div>
  );
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
    <div className="flex max-w-2xl flex-col gap-6">
      <Link href={`${TRADES}?type=sales`} className="text-fg-muted text-sm hover:underline">
        ← {t("back")}
      </Link>
      <h1 className="text-3xl font-bold">{t("number", { number })}</h1>
      {body}
    </div>
  );
}
