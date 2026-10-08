"use client";

import { Button, buttonVariants } from "@csmarket/ui";
import { useTranslations } from "next-intl";
import { useMemo } from "react";

import { OrderRow, SaleRow } from "./TradeRow";
import { useTradesFeed, type TradesType } from "./useTradesFeed";

import { HistoryFilter } from "@/components/account/HistoryFilter";
import { Link } from "@/i18n/navigation";
import { useAuth } from "@/lib/auth";
import { HOME, TRADES } from "@/lib/paths";

export type { TradesType } from "./useTradesFeed";

interface TradesViewProps {
  locale: string;
  type: TradesType;
}

/** «Обмены»: purchases and sales in one list, newest first; «В холде» — sales whose money waits. */
export function TradesView({ locale, type }: TradesViewProps) {
  const t = useTranslations("web.trades");
  return (
    <div className="flex flex-col gap-5">
      <HistoryFilter
        current={type}
        options={[
          { key: "all", label: t("all"), href: TRADES },
          { key: "purchases", label: t("purchases"), href: `${TRADES}?type=purchases` },
          { key: "sales", label: t("sales"), href: `${TRADES}?type=sales` },
          { key: "hold", label: t("hold"), href: `${TRADES}?type=hold` },
        ]}
      />
      <TradesList locale={locale} type={type} />
    </div>
  );
}

function TradesList({ locale, type }: TradesViewProps) {
  const t = useTranslations("web.trades");
  const orders = useTranslations("web.orders");
  const nav = useTranslations("web.nav");
  const authT = useTranslations("web.auth");
  const common = useTranslations("common");
  const { status, user, signInHref } = useAuth();
  const signedIn = status === "signed_in" && user !== null;
  const feed = useTradesFeed(type, signedIn);
  const when = useMemo(
    () =>
      new Intl.DateTimeFormat(locale, {
        day: "numeric",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
      }),
    [locale],
  );

  if (status === "loading") return <Skeleton />;
  if (status === "suspended") return <p className="text-danger">{authT("suspended")}</p>;
  if (!signedIn) {
    return (
      <div className="flex flex-col items-start gap-4">
        <p className="text-fg-muted">{orders("signedOut")}</p>
        <a href={signInHref(locale)} className={buttonVariants({ size: "lg" })}>
          {nav("signIn")}
        </a>
      </div>
    );
  }
  if (feed.status === "pending") return <Skeleton />;
  if (feed.status === "error") {
    return (
      <div className="flex flex-col items-start gap-3">
        <p className="text-fg-muted">{common("errors.generic")}</p>
        <Button variant="secondary" onClick={feed.retry}>
          {common("actions.retry")}
        </Button>
      </div>
    );
  }
  const { entries, next } = feed.merged;
  if (entries.length === 0) {
    return (
      <div className="flex flex-col items-start gap-4">
        <p className="text-fg-muted">
          {type === "hold" ? t("holdEmpty") : type === "sales" ? t("salesEmpty") : t("empty")}
        </p>
        {type === "all" || type === "purchases" ? (
          <Link href={HOME} className={buttonVariants({ variant: "secondary" })}>
            {orders("toCatalog")}
          </Link>
        ) : null}
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-4">
      <ul className="flex flex-col gap-2">
        {entries.map((e) => (
          <li key={e.kind === "order" ? `o-${e.order.number}` : `s-${e.sale.number}`}>
            {e.kind === "order" ? (
              <OrderRow order={e.order} locale={locale} when={when} />
            ) : (
              <SaleRow sale={e.sale} locale={locale} when={when} />
            )}
          </li>
        ))}
      </ul>
      {next.length > 0 ? (
        <Button
          variant="secondary"
          className="self-start"
          disabled={feed.fetchingMore}
          onClick={feed.more}
        >
          {t("more")}
        </Button>
      ) : null}
    </div>
  );
}

function Skeleton() {
  return <div aria-busy className="bg-surface h-40 animate-pulse rounded-xl" />;
}
