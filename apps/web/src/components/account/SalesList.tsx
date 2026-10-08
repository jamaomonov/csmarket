"use client";

import { Button } from "@csmarket/ui";
import { formatUzs } from "@csmarket/utils";
import { useInfiniteQuery, type InfiniteData } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useMemo } from "react";

import { Link } from "@/i18n/navigation";
import { useAuth } from "@/lib/auth";
import { salePath } from "@/lib/paths";
import { listSales, SALES_KEY, type SaleOut, type SalesPage } from "@/lib/sales";

interface SalesListProps {
  locale: string;
}

/** The status word of a sale; a card sale's payout refines «payout». */
export function saleLabel(sale: SaleOut): string {
  return sale.status === "payout" && sale.payout_status
    ? `payout.${sale.payout_status}`
    : `status.${sale.status}`;
}

/** «Продажи»: the seller's sales, newest first, one page at a time. */
export function SalesList({ locale }: SalesListProps) {
  const t = useTranslations("web.sales");
  const trades = useTranslations("web.trades");
  const { status, user } = useAuth();
  const signedIn = status === "signed_in" && user !== null;
  const sales = useInfiniteQuery<
    SalesPage,
    Error,
    InfiniteData<SalesPage, string | null>,
    typeof SALES_KEY,
    string | null
  >({
    queryKey: SALES_KEY,
    queryFn: ({ pageParam }) => listSales(pageParam ?? undefined),
    initialPageParam: null,
    getNextPageParam: (last) => last.next_cursor,
    enabled: signedIn,
  });
  const when = useMemo(() => new Intl.DateTimeFormat(locale, { dateStyle: "medium" }), [locale]);
  const skeleton = <div aria-busy className="bg-surface h-24 animate-pulse rounded-lg" />;
  // Signed out: the orders list above asks to sign in; nothing to show here.
  if (!signedIn) return status === "loading" ? skeleton : null;
  if (sales.isPending) return skeleton;
  if (sales.isError) return <p className="text-fg-muted">{t("listFailed")}</p>;
  const items = sales.data.pages.flatMap((p) => p.items);
  if (items.length === 0) return <p className="text-fg-muted">{trades("salesEmpty")}</p>;
  return (
    <div className="flex flex-col gap-4">
      <ul className="flex flex-col gap-3">
        {items.map((s) => {
          const [first] = s.items;
          return (
            <li key={s.number}>
              <Link
                href={salePath(s.number)}
                data-testid="sale-card"
                data-state={s.status}
                className="border-border hover:border-border-strong flex flex-col gap-2 rounded-lg border p-4"
              >
                <span className="flex justify-between gap-3">
                  <span className="min-w-0 truncate font-medium">
                    {first?.name}
                    {s.items.length > 1 ? (
                      <span className="text-fg-dim"> +{s.items.length - 1}</span>
                    ) : null}
                  </span>
                  <span className="num text-accent shrink-0 font-semibold">
                    {formatUzs(locale, s.payout_uzs)}
                  </span>
                </span>
                <span className="text-fg-dim flex justify-between text-sm">
                  <span className="text-fg-muted font-semibold">{t(saleLabel(s))}</span>
                  <span>
                    {t("number", { number: s.number })} ·{" "}
                    <time dateTime={s.created_at}>{when.format(new Date(s.created_at))}</time>
                  </span>
                </span>
              </Link>
            </li>
          );
        })}
      </ul>
      {sales.hasNextPage ? (
        <Button
          variant="secondary"
          className="self-start"
          disabled={sales.isFetchingNextPage}
          onClick={() => void sales.fetchNextPage()}
        >
          {t("more")}
        </Button>
      ) : null}
    </div>
  );
}
