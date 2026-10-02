"use client";

import { Button, buttonVariants } from "@csmarket/ui";
import { formatUzs } from "@csmarket/utils";
import { useInfiniteQuery, type InfiniteData } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useMemo } from "react";

import { OrderItem } from "@/components/order/OrderItem";
import { Link } from "@/i18n/navigation";
import { useAuth } from "@/lib/auth";
import { listOrders, ORDERS_KEY, type OrderOut, type OrdersPage } from "@/lib/orders";
import { HOME, orderPath } from "@/lib/paths";

interface OrdersListProps {
  locale: string;
}

/** «Мои заказы»: the buyer's orders, newest first, one page at a time behind «Показать ещё». */
export function OrdersList({ locale }: OrdersListProps) {
  const t = useTranslations("web.orders");
  const nav = useTranslations("web.nav");
  const authT = useTranslations("web.auth");
  const { status, user, signInHref } = useAuth();
  const signedIn = status === "signed_in" && user !== null;
  const orders = useInfiniteQuery<
    OrdersPage,
    Error,
    InfiniteData<OrdersPage, string | null>,
    typeof ORDERS_KEY,
    string | null
  >({
    queryKey: ORDERS_KEY,
    queryFn: ({ pageParam }) => listOrders(pageParam ?? undefined),
    initialPageParam: null,
    getNextPageParam: (last) => last.next_cursor,
    enabled: signedIn,
  });
  const when = useMemo(
    () => new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short" }),
    [locale],
  );

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
  if (orders.isPending) return <Skeleton />;
  if (orders.isError) return <Failed onRetry={() => void orders.refetch()} />;

  const items = orders.data.pages.flatMap((page) => page.items);
  if (items.length === 0) {
    return (
      <div className="flex flex-col items-start gap-4">
        <p className="text-fg-muted">{t("empty")}</p>
        <Link href={HOME} className={buttonVariants({ variant: "secondary" })}>
          {t("toCatalog")}
        </Link>
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-4">
      <ul className="flex flex-col gap-3">
        {items.map((order) => (
          <li key={order.number}>
            <OrderCard order={order} locale={locale} when={when} />
          </li>
        ))}
      </ul>
      {orders.hasNextPage ? (
        <Button
          variant="secondary"
          className="self-start"
          disabled={orders.isFetchingNextPage}
          onClick={() => {
            void orders.fetchNextPage();
          }}
        >
          {t("more")}
        </Button>
      ) : null}
    </div>
  );
}

interface OrderCardProps {
  order: OrderOut;
  locale: string;
  /** The order date's format, built once per list. */
  when: Intl.DateTimeFormat;
}

function OrderCard({ order, locale, when }: OrderCardProps) {
  const t = useTranslations("web.orders");
  return (
    <Link
      href={orderPath(order.number)}
      data-testid="order-card"
      data-state={order.status}
      className="border-border hover:border-border-strong flex flex-col gap-3 rounded-lg border p-4"
    >
      <OrderItem order={order} price={formatUzs(locale, order.price_uzs)} linked={false} />
      <p className="text-fg-dim flex flex-wrap justify-between gap-2 text-sm">
        <span className="text-fg-muted font-semibold">{t(`status.${order.status}`)}</span>
        <span>
          {t("number", { number: order.number })} ·{" "}
          <time dateTime={order.created_at}>{when.format(new Date(order.created_at))}</time>
        </span>
      </p>
    </Link>
  );
}

function Skeleton() {
  return <div aria-busy className="bg-surface h-40 animate-pulse rounded-lg" />;
}

function Failed({ onRetry }: { onRetry: () => void }) {
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
