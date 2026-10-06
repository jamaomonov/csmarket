"use client";

import { Button } from "@csmarket/ui";
import { formatUzs } from "@csmarket/utils";
import { X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useMemo, useState } from "react";

import { SellCart } from "./SellCart";
import { SellItemCard } from "./SellItemCard";
import { SellToolbar, type SellSort } from "./SellToolbar";

import { TradeLinkForm } from "@/components/account/TradeLinkForm";
import { useAuth } from "@/lib/auth";
import { sellSummary, type PayoutMethod, type SellItem } from "@/lib/sell";

interface SellViewProps {
  locale: string;
  inventory: SellItem[];
}

const ORDER: Record<SellSort, (a: SellItem, b: SellItem) => number> = {
  expensive: (a, b) => b.priceUzs - a.priceUzs,
  cheap: (a, b) => a.priceUzs - b.priceUzs,
  name: (a, b) => a.name.localeCompare(b.name),
};

/** «Продайте скины»: the inventory to pick from, and a cart with the payout beside it. */
export function SellView({ locale, inventory }: SellViewProps) {
  const t = useTranslations("web.sell");
  const nav = useTranslations("web.nav");
  const { status, user, signInHref, refreshMe } = useAuth();
  const [chosen, setChosen] = useState<ReadonlySet<string>>(new Set());
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<SellSort>("expensive");
  const [category, setCategory] = useState<string | null>(null);
  const [method, setMethod] = useState<PayoutMethod>("balance");
  const [card, setCard] = useState("");
  const [sheet, setSheet] = useState(false);

  const sellable = inventory.filter((x) => x.unavailable === null);
  const categories = useMemo(() => [...new Set(inventory.map((x) => x.category))], [inventory]);
  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (
      inventory
        .filter(
          (x) => (category === null || x.category === category) && x.name.toLowerCase().includes(q),
        )
        // Sellable first, then the chosen order.
        .sort(
          (a, b) =>
            Number(a.unavailable !== null) - Number(b.unavailable !== null) || ORDER[sort](a, b),
        )
    );
  }, [inventory, query, category, sort]);
  const picked = inventory.filter((x) => chosen.has(x.assetId));
  const allChosen = sellable.length > 0 && picked.length === sellable.length;
  const toggle = (id: string) => {
    setChosen((cur) => {
      const next = new Set(cur);
      if (!next.delete(id)) next.add(id);
      return next;
    });
  };
  const uzs = (n: number) => formatUzs(locale, n);

  let body;
  if (status === "loading") {
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
        <TradeLinkForm
          initial={{ trade_link: null, verdict: null, reason: null }}
          onChange={() => {
            void refreshMe();
          }}
        />
      </div>
    );
  } else {
    const cart = (
      <SellCart
        locale={locale}
        chosen={picked}
        onRemove={toggle}
        method={method}
        onMethod={setMethod}
        card={card}
        onCard={setCard}
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
              setChosen(allChosen ? new Set() : new Set(sellable.map((x) => x.assetId)));
            }}
          />
          <p className="text-fg-muted text-sm">
            {t("total", {
              count: inventory.length,
              sum: uzs(inventory.reduce((a, x) => a + x.priceUzs, 0)),
            })}
            <span aria-hidden className="text-fg-dim">
              {" · "}
            </span>
            <span className="text-fg-dim">{t("available", { count: sellable.length })}</span>
          </p>
          {shown.length === 0 ? (
            <p className="text-fg-muted py-16 text-center">{t("empty")}</p>
          ) : (
            <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 xl:grid-cols-4">
              {shown.map((x) => (
                <SellItemCard
                  key={x.assetId}
                  item={x}
                  locale={locale}
                  selected={chosen.has(x.assetId)}
                  onToggle={() => {
                    toggle(x.assetId);
                  }}
                />
              ))}
            </div>
          )}
        </div>
        <div className="hidden lg:sticky lg:top-4 lg:block">{cart}</div>
        {/* Phones: a bar with the count and the sum; the cart opens as a sheet. */}
        {picked.length > 0 ? (
          <div className="bg-surface border-border fixed inset-x-0 bottom-0 z-30 flex items-center gap-3 border-t p-3 lg:hidden">
            <span className="flex-1 text-sm font-semibold">
              {t("cart.title", { count: picked.length })}
              <span className="text-accent num block">
                {uzs(
                  sellSummary(
                    picked.map((x) => x.priceUzs),
                    method,
                  ).payout,
                )}
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
