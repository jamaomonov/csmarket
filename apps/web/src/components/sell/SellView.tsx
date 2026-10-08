"use client";

import { Button } from "@csmarket/ui";
import { formatUzs } from "@csmarket/utils";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useMemo, useState } from "react";

import { SellCart } from "./SellCart";
import { SellItemCard } from "./SellItemCard";
import { SellToolbar, type SellSort } from "./SellToolbar";

import { TradeLinkForm } from "@/components/account/TradeLinkForm";
import { useAuth } from "@/lib/auth";
import {
  getInventory,
  INVENTORY_KEY,
  sellError,
  sellSummary,
  type Inventory,
  type Payout,
  type SellConfig,
  type SellItem,
} from "@/lib/sell";

interface SellViewProps {
  locale: string;
  config: SellConfig;
}

const price = (x: SellItem): number => Number(x.price_uzs);
const ORDER: Record<SellSort, (a: SellItem, b: SellItem) => number> = {
  expensive: (a, b) => price(b) - price(a),
  cheap: (a, b) => price(a) - price(b),
  name: (a, b) => a.name.localeCompare(b.name),
};
const NO_ITEMS: SellItem[] = [];

/** «Продайте скины»: the items we buy now, and a cart with the payout beside them. */
export function SellView({ locale, config }: SellViewProps) {
  const t = useTranslations("web.sell");
  const nav = useTranslations("web.nav");
  const { status, user, signInHref, refreshMe } = useAuth();
  const ready = status === "signed_in" && user !== null && Boolean(user.trade_link);
  const qc = useQueryClient();
  const inventory = useQuery({
    queryKey: INVENTORY_KEY,
    queryFn: () => getInventory(),
    enabled: ready,
    retry: false,
  });
  const [chosen, setChosen] = useState<ReadonlySet<string>>(new Set());
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<SellSort>("expensive");
  const [category, setCategory] = useState<string | null>(null);
  const [payout, setPayout] = useState<Payout>({ to: "balance" });
  const [sheet, setSheet] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  const items = inventory.data?.items ?? NO_ITEMS;
  const maxItems = inventory.data?.max_items ?? 0;
  const categories = useMemo(
    () => [...new Set(items.flatMap((x) => (x.category ? [x.category] : [])))],
    [items],
  );
  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return items
      .filter(
        (x) => (category === null || x.category === category) && x.name.toLowerCase().includes(q),
      )
      .sort(ORDER[sort]);
  }, [items, query, category, sort]);
  const picked = items.filter((x) => chosen.has(x.asset_id));
  const allChosen = items.length > 0 && picked.length === Math.min(items.length, maxItems);
  const toggle = (id: string) => {
    setChosen((cur) => {
      const next = new Set(cur);
      if (!next.delete(id) && next.size < maxItems) next.add(id);
      return next;
    });
  };
  const reload = async () => {
    setRefreshing(true);
    try {
      const fresh: Inventory = await getInventory(true);
      qc.setQueryData(INVENTORY_KEY, fresh);
      setChosen(
        (cur) => new Set([...cur].filter((id) => fresh.items.some((x) => x.asset_id === id))),
      );
    } catch {
      await inventory.refetch();
    } finally {
      setRefreshing(false);
    }
  };
  const uzs = (n: number) => formatUzs(locale, n);

  let body;
  if (status === "loading" || (ready && inventory.isPending)) {
    body = <div aria-busy className="bg-surface h-96 animate-pulse rounded-xl" />;
  } else if (status !== "signed_in" || !user) {
    body = (
      <div className="bg-surface flex flex-col items-start gap-4 rounded-xl p-6">
        <p className="text-fg-muted">{t("signedOut")}</p>
        <a
          href={signInHref(locale)}
          className="bg-accent text-accent-fg rounded-md px-5 py-3 font-semibold"
        >
          {nav("signIn")}
        </a>
      </div>
    );
  } else if (!user.trade_link) {
    body = (
      <div className="flex max-w-2xl flex-col gap-3">
        <p className="text-fg-muted">{t("needTradeLink")}</p>
        <div className="bg-surface rounded-xl">
          <TradeLinkForm
            initial={{ trade_link: null, verdict: null, reason: null }}
            onChange={() => {
              void refreshMe();
            }}
          />
        </div>
      </div>
    );
  } else if (inventory.isError || !inventory.data) {
    const refusal = sellError(inventory.error);
    const reason = refusal?.reason ?? "other";
    body = (
      <div className="bg-surface flex flex-col items-start gap-4 rounded-xl p-6">
        <p className="text-fg-muted">
          {refusal?.code === "steam_refused"
            ? t.has(`steam.${reason}`)
              ? t(`steam.${reason}`)
              : t("steam.other")
            : t("loadFailed")}
        </p>
        <Button variant="secondary" onClick={() => void reload()}>
          {t("retry")}
        </Button>
      </div>
    );
  } else {
    const cart = (
      <SellCart
        locale={locale}
        config={config}
        inventory={inventory.data}
        chosen={picked}
        onRemove={toggle}
        payout={payout}
        onPayout={setPayout}
        onPricesChanged={() => void reload()}
      />
    );
    body = (
      <div className="grid grid-cols-1 items-start gap-5 lg:grid-cols-[minmax(0,1fr)_380px]">
        <div className="flex min-w-0 flex-col gap-4">
          <SellToolbar
            query={query}
            onQuery={setQuery}
            sort={sort}
            onSort={setSort}
            categories={categories}
            category={category}
            onCategory={setCategory}
            allChosen={allChosen}
            onToggleAll={() => {
              setChosen(
                allChosen ? new Set() : new Set(shown.slice(0, maxItems).map((x) => x.asset_id)),
              );
            }}
            onRefresh={() => void reload()}
            refreshing={refreshing}
          />
          <p className="text-fg-muted text-sm">
            {t("total", { count: items.length, sum: uzs(items.reduce((a, x) => a + price(x), 0)) })}
          </p>
          {shown.length === 0 ? (
            <p className="text-fg-muted py-16 text-center">
              {items.length === 0 ? t("emptyInventory") : t("empty")}
            </p>
          ) : (
            <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 xl:grid-cols-4">
              {shown.map((x) => (
                <SellItemCard
                  key={x.asset_id}
                  item={x}
                  locale={locale}
                  selected={chosen.has(x.asset_id)}
                  onToggle={() => {
                    toggle(x.asset_id);
                  }}
                />
              ))}
            </div>
          )}
          <p className="text-fg-dim text-sm">{t("shownNote")}</p>
          {picked.length >= maxItems && maxItems > 0 ? (
            <p className="text-fg-dim text-sm">{t("cart.max", { count: maxItems })}</p>
          ) : null}
        </div>
        <div className="hidden lg:sticky lg:top-4 lg:block">{cart}</div>
        {picked.length > 0 ? (
          <div className="bg-surface border-border fixed inset-x-0 bottom-0 z-30 flex items-center gap-3 border-t p-3 lg:hidden">
            <span className="flex-1 text-sm font-semibold">
              {t("cart.title", { count: picked.length })}
              <span className="text-accent num block">
                {uzs(sellSummary(picked.map(price), payout, config).payout)}
              </span>
            </span>
            <Button
              onClick={() => {
                setSheet(true);
              }}
            >
              {t("continue")}
            </Button>
          </div>
        ) : null}
        {sheet ? (
          <div className="bg-bg/80 fixed inset-0 z-40 overflow-y-auto p-3 backdrop-blur lg:hidden">
            <div className="mb-2 flex justify-end">
              <button
                type="button"
                aria-label={t("close")}
                onClick={() => {
                  setSheet(false);
                }}
                className="bg-surface grid size-10 place-items-center rounded-lg"
              >
                <X className="size-5" aria-hidden />
              </button>
            </div>
            {cart}
          </div>
        ) : null}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6 pb-24 lg:pb-0">
      <h1 className="text-center text-3xl font-bold">{t("title")}</h1>
      {body}
    </div>
  );
}
