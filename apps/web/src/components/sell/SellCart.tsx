"use client";

import { Button, cn } from "@csmarket/ui";
import { formatUzs } from "@csmarket/utils";
import { X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useId } from "react";

import { CARD_BRANDS, PayoutPicker } from "./PayoutPicker";

import {
  BALANCE_BONUS_PERCENT,
  CARD_MIN_UZS,
  cardDigits,
  cardFits,
  formatCard,
  SELL_FEE_PERCENT,
  sellSummary,
  type PayoutMethod,
  type SellItem,
} from "@/lib/sell";

interface SellCartProps {
  locale: string;
  chosen: SellItem[];
  onRemove: (assetId: string) => void;
  method: PayoutMethod;
  onMethod: (m: PayoutMethod) => void;
  card: string;
  onCard: (digits: string) => void;
}

const Row = ({ label, value, strong }: { label: string; value: string; strong?: boolean }) => (
  <p className={cn("flex items-baseline gap-3", strong ? "text-base font-bold" : "text-sm")}>
    <span className={strong ? "text-fg" : "text-fg-muted"}>{label}</span>
    <span aria-hidden className="border-border flex-1 border-b border-dashed" />
    <span
      className={cn("num", strong && "text-accent")}
      {...(strong ? { "data-testid": "sell-payout" } : {})}
    >
      {value}
    </span>
  </p>
);

/** The chosen skins, where the money goes and what reaches the seller. */
export function SellCart({
  locale,
  chosen,
  onRemove,
  method,
  onMethod,
  card,
  onCard,
}: SellCartProps) {
  const t = useTranslations("web.sell");
  const cardId = useId();
  const sum = sellSummary(
    chosen.map((x) => x.priceUzs),
    method,
  );
  const uzs = (n: number) => formatUzs(locale, n);
  const toCard = method !== "balance";
  const wrongCard = toCard && card.length >= 4 && !cardFits(method, card.padEnd(16, "0"));
  const belowMin = toCard && sum.payout > 0 && sum.payout < CARD_MIN_UZS;
  const title = t("cart.title", { count: chosen.length });
  return (
    <aside aria-label={title} className="bg-surface flex flex-col gap-5 rounded-xl p-5">
      <h2 className="text-lg font-bold">
        {title}
        {chosen.length > 0 ? <span className="text-accent num"> · {uzs(sum.items)}</span> : null}
      </h2>

      {chosen.length === 0 ? (
        <p className="text-fg-muted text-sm">{t("cart.hint")}</p>
      ) : (
        <ul className="-mr-2 flex max-h-56 flex-col gap-1.5 overflow-y-auto pr-2">
          {chosen.map((x) => (
            <li key={x.assetId} className="bg-surface-2 flex items-center gap-3 rounded-lg p-2">
              {/* eslint-disable-next-line @next/next/no-img-element -- Steam CDN images */}
              <img src={x.imageUrl} alt="" className="h-8 w-12 shrink-0 object-contain" />
              <span className="min-w-0 flex-1 truncate text-[13px]">{x.name}</span>
              <span className="num shrink-0 text-[13px] font-semibold">{uzs(x.priceUzs)}</span>
              <button
                type="button"
                aria-label={t("cart.remove", { name: x.name })}
                onClick={() => {
                  onRemove(x.assetId);
                }}
                className="text-fg-dim hover:text-fg rounded p-0.5"
              >
                <X className="size-4" aria-hidden />
              </button>
            </li>
          ))}
        </ul>
      )}

      <PayoutPicker method={method} onPick={onMethod} />

      {toCard ? (
        <div>
          <label htmlFor={cardId} className="text-fg-muted mb-2 block text-sm font-semibold">
            {t("card.label", { method: CARD_BRANDS[method] })}
          </label>
          <input
            id={cardId}
            inputMode="numeric"
            autoComplete="cc-number"
            placeholder="0000 0000 0000 0000"
            value={formatCard(card)}
            onChange={(e) => {
              onCard(cardDigits(e.target.value));
            }}
            aria-invalid={wrongCard}
            className={cn(
              "bg-bg num h-12 w-full rounded-lg border px-4 text-lg tracking-wider outline-none",
              wrongCard ? "border-danger" : "border-border focus:border-accent",
            )}
          />
          {wrongCard ? (
            <p className="text-danger mt-2 text-sm">
              {t("card.wrong", { method: CARD_BRANDS[method] })}
            </p>
          ) : (
            <p className={cn("mt-2 text-sm", belowMin ? "text-danger" : "text-fg-dim")}>
              {t("card.min", { sum: uzs(CARD_MIN_UZS) })}
            </p>
          )}
        </div>
      ) : null}

      <div className="flex flex-col gap-2">
        <Row label={t("summary.items")} value={uzs(sum.items)} />
        {toCard ? (
          <Row label={t("summary.fee", { percent: SELL_FEE_PERCENT })} value={`−${uzs(sum.fee)}`} />
        ) : (
          <Row
            label={t("summary.bonus", { percent: BALANCE_BONUS_PERCENT })}
            value={`+${uzs(sum.bonus)}`}
          />
        )}
        <Row label={t("summary.payout")} value={uzs(sum.payout)} strong />
      </div>

      {/* Selling opens with its API; until then the button says so (owner, 2026-10-06). */}
      <Button size="lg" disabled>
        {t("soon")}
      </Button>
    </aside>
  );
}
