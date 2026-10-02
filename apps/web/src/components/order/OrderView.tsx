"use client";

import { SessionApiError } from "@csmarket/api-client";
import { DEFAULT_LOCALE, isLocale } from "@csmarket/i18n";
import { Button, buttonVariants } from "@csmarket/ui";
import { assertNever, formatUzs } from "@csmarket/utils";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useEffect, type ReactNode } from "react";

import { OrderItem } from "./OrderItem";
import { OrderPay } from "./OrderPay";
import { SkinTradeCard } from "./SkinTradeCard";
import { useArrivalKassa, useKassaAutoOpen } from "./useOrderArrival";

import type { Locale } from "@csmarket/i18n";

import { ENTRIES_KEY } from "@/components/balance/EntriesList";
import { Link } from "@/i18n/navigation";
import { useAuth } from "@/lib/auth";
import { BALANCE_KEY } from "@/lib/balance";
import { orderPollInterval } from "@/lib/order-poll";
import {
  getOrder,
  orderKey,
  ORDERS_KEY,
  type OrderOut,
  type PayProvider,
  type SkinTradeOut,
} from "@/lib/orders";
import { ORDERS } from "@/lib/paths";

const isNotFound = (err: unknown): boolean => err instanceof SessionApiError && err.status === 404;

/** A paid order the API has no trade row for yet is being bought. */
const BUYING: SkinTradeOut = {
  state: "buying",
  reason_code: null,
  offer_url: null,
  send_until: null,
  release_date: null,
  seller: null,
  refunded_to: null,
};

interface OrderViewProps {
  locale: string;
  number: string;
}

/**
 * An order's page: pay it while it is pending, then follow the Steam trade. It re-reads
 * the order until it can no longer change (`orderPollInterval`) — a socket nudge
 * (`useOrderSocket`) only re-reads it sooner; with `?go=1` it opens
 * the chosen kassa once, so on a phone the tab left behind the bank app is this page.
 */
export function OrderView({ locale, number }: OrderViewProps) {
  const t = useTranslations("web.orders");
  const nav = useTranslations("web.nav");
  const authT = useTranslations("web.auth");
  const { status, user, signInHref } = useAuth();
  const signedIn = status === "signed_in" && user !== null;
  const apiLocale = isLocale(locale) ? locale : DEFAULT_LOCALE;
  const kassa = useArrivalKassa();
  const qc = useQueryClient();

  const order = useQuery({
    queryKey: orderKey(number),
    queryFn: () => getOrder(number),
    enabled: signedIn,
    retry: (failures, err) => !isNotFound(err) && failures < 2,
    refetchOnWindowFocus: true,
    refetchInterval: (query) => {
      const data = query.state.data;
      return data ? orderPollInterval(data.status, query.state.fetchFailureCount) : false;
    },
  });

  useKassaAutoOpen(number, order.data, kassa, apiLocale);

  // A payment from the balance or a refund to it moves the balance and the list.
  const shown = order.data?.status;
  useEffect(() => {
    if (shown === undefined) return;
    void qc.invalidateQueries({ queryKey: BALANCE_KEY });
    void qc.invalidateQueries({ queryKey: ENTRIES_KEY });
    void qc.invalidateQueries({ queryKey: ORDERS_KEY });
  }, [shown, qc]);

  if (status === "loading") return <Skeleton />;
  if (status === "suspended") return <p className="text-danger">{authT("suspended")}</p>;
  if (!signedIn) {
    return (
      <div className="flex flex-col items-start gap-4">
        <p className="text-fg-muted">{t("signedOut")}</p>
        <a href={signInHref(locale)} className={buttonVariants({ size: "lg" })}>
          {nav("signIn")}
        </a>
      </div>
    );
  }
  if (!order.data) {
    if (!order.isError) return <Skeleton />;
    if (isNotFound(order.error)) {
      return (
        <Panel state="notFound">
          <h1 className="text-2xl font-bold">{t("notFound")}</h1>
        </Panel>
      );
    }
    return (
      <FetchFailed
        onRetry={() => {
          void order.refetch();
        }}
      />
    );
  }

  const data = order.data;
  return (
    <Panel state={data.status}>
      <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h1 className="text-2xl font-bold">{t("number", { number: data.number })}</h1>
        <span data-testid="order-status-label" className="text-fg-muted text-sm font-semibold">
          {t(`status.${data.status}`)}
        </span>
      </header>
      <OrderItem order={data} price={formatUzs(locale, data.price_uzs)} />
      <OrderBody
        order={data}
        locale={apiLocale}
        kassa={kassa}
        onPaid={() => {
          void order.refetch();
        }}
      />
    </Panel>
  );
}

interface OrderBodyProps {
  order: OrderOut;
  locale: Locale;
  kassa: PayProvider | null;
  onPaid: () => void;
}

function OrderBody({ order, locale, kassa, onPaid }: OrderBodyProps) {
  const t = useTranslations("web.orders");
  switch (order.status) {
    case "pending":
      return order.payable ? (
        <OrderPay order={order} locale={locale} initial={kassa} onPaid={onPaid} />
      ) : (
        <p className="text-lg font-semibold">{t("expired")}</p>
      );
    case "cancelled":
      // Only the expiry sweep cancels an order; one never paid simply ran out of time.
      return (
        <p className="text-lg font-semibold">
          {t(order.paid_at === null ? "expired" : "cancelled")}
        </p>
      );
    case "paid":
    case "buying":
    case "trade_sent":
    case "delivered":
    case "failed":
    case "returned":
      return <SkinTradeCard trade={order.trade ?? BUYING} locale={locale} />;
    default:
      return assertNever(order.status);
  }
}

interface PanelProps {
  /** An order status, or `notFound`. */
  state: string;
  children: ReactNode;
}

function Panel({ state, children }: PanelProps) {
  const t = useTranslations("web.orders");
  return (
    <section
      data-testid="order-status"
      data-state={state}
      aria-live="polite"
      className="flex flex-col items-start gap-5"
    >
      {children}
      <Link href={ORDERS} className="text-fg-muted hover:text-fg text-sm">
        {t("title")}
      </Link>
    </section>
  );
}

function Skeleton() {
  return <div aria-busy className="bg-surface h-40 animate-pulse rounded-lg" />;
}

interface FetchFailedProps {
  onRetry: () => void;
}

function FetchFailed({ onRetry }: FetchFailedProps) {
  const common = useTranslations("common");
  return (
    <div className="flex flex-col items-start gap-3">
      <p className="text-fg-muted">{common("errors.generic")}</p>
      <Button variant="secondary" onClick={onRetry}>
        {common("actions.retry")}
      </Button>
    </div>
  );
}
