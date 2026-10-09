"use client";

import { Button, cn } from "@csmarket/ui";
import { useInfiniteQuery, type InfiniteData } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { getEntries, signedUsd, signedUzs, type EntriesPage, type EntryType } from "@/lib/balance";

interface EntriesListProps {
  locale: string;
  /** Only top-ups or only withdrawals; everything when absent. */
  type?: EntryType;
  /** The USD wallet's lines instead of the soʻm balance's. */
  currency?: "usd";
}

/** Query key of the balance history, for whoever needs to invalidate it. */
export const ENTRIES_KEY = ["wallet", "entries"] as const;

/** The balance history, newest first, one page at a time behind «Показать ещё». */
export function EntriesList({ locale, type, currency }: EntriesListProps) {
  const t = useTranslations("web.balance");
  const common = useTranslations("common");
  const tx = useTranslations("web.transactions");
  const entries = useInfiniteQuery<
    EntriesPage,
    Error,
    InfiniteData<EntriesPage, string | null>,
    readonly [...typeof ENTRIES_KEY, string],
    string | null
  >({
    // Under ENTRIES_KEY, so invalidating that refreshes every filter.
    queryKey: [...ENTRIES_KEY, currency === "usd" ? "usd" : (type ?? "all")],
    queryFn: ({ pageParam }) =>
      currency
        ? getEntries(pageParam ?? undefined, type, currency)
        : getEntries(pageParam ?? undefined, type),
    initialPageParam: null,
    getNextPageParam: (last) => last.next_cursor,
  });
  const when = new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short" });

  let body;
  if (entries.isPending) {
    body = <div aria-busy className="bg-surface h-24 animate-pulse rounded-md" />;
  } else if (entries.isError) {
    body = (
      <div className="flex flex-col items-start gap-2">
        <p className="text-fg-muted text-sm">{common("errors.generic")}</p>
        <Button
          variant="secondary"
          size="sm"
          onClick={() => {
            void entries.refetch();
          }}
        >
          {common("actions.retry")}
        </Button>
      </div>
    );
  } else {
    const items = entries.data.pages.flatMap((page) => page.items);
    body =
      items.length === 0 ? (
        <p className="text-fg-muted text-sm">
          {type === "withdrawal" ? tx("withdrawalsEmpty") : t("historyEmpty")}
        </p>
      ) : (
        <ul className="divide-border divide-y">
          {items.map((e) => (
            <li key={e.id} className="flex items-center justify-between gap-4 py-3">
              <div className="min-w-0">
                <p className="font-semibold">{t(`kind.${e.kind}`)}</p>
                <p className="text-fg-dim text-xs">
                  <time dateTime={e.created_at}>{when.format(new Date(e.created_at))}</time>
                  {e.reference_number ? ` · ${e.reference_number}` : null}
                </p>
              </div>
              <p
                data-testid="entry-amount"
                className={cn(
                  "shrink-0 font-bold tabular-nums",
                  (e.amount_usd ?? e.amount_uzs).startsWith("-") ? "text-fg" : "text-success",
                )}
              >
                {e.amount_usd !== null ? signedUsd(e.amount_usd) : signedUzs(locale, e.amount_uzs)}
              </p>
            </li>
          ))}
        </ul>
      );
  }

  return (
    <section className="border-border rounded-lg border p-5">
      <h2 className="text-lg font-bold">
        {currency === "usd" ? t("usd.historyTitle") : t("historyTitle")}
      </h2>
      <div className="mt-3">{body}</div>
      {entries.hasNextPage ? (
        <Button
          variant="secondary"
          className="mt-3"
          disabled={entries.isFetchingNextPage}
          onClick={() => {
            void entries.fetchNextPage();
          }}
        >
          {t("historyMore")}
        </Button>
      ) : null}
    </section>
  );
}
