"use client";

import { cn, LogoMark } from "@csmarket/ui";
import { useTranslations } from "next-intl";

import type { SavedCard } from "@/lib/sales";

import { CARD_TYPES, type CardType, type Payout, type SellConfig } from "@/lib/sell";

/** The card brands' names, never translated, and their logos in `public/payout/`. */
export const CARD_BRANDS: Readonly<Record<CardType, string>> = {
  uzcard: "Uzcard",
  humo: "Humo",
  uzum_visa: "Uzum Visa",
};
export const CARD_LOGOS: Readonly<Record<CardType, string>> = {
  uzcard: "/payout/uzcard.png",
  humo: "/payout/humo.png",
  uzum_visa: "/payout/uzum-visa.png",
};

interface PayoutPickerProps {
  config: SellConfig;
  cards: SavedCard[];
  value: Payout;
  onPick: (payout: Payout) => void;
}

interface Option {
  key: string;
  payout: Payout;
  name: string;
  note: string;
  type: CardType | null;
}

const same = (a: Payout, b: Payout): boolean =>
  a.to === b.to &&
  (a.to !== "saved" || (b.to === "saved" && a.cardId === b.cardId)) &&
  (a.to !== "new" || (b.to === "new" && a.type === b.type));

/** Where the money goes: the balance (a bonus), a saved card or a new one (a fee). Radios. */
export function PayoutPicker({ config, cards, value, onPick }: PayoutPickerProps) {
  const t = useTranslations("web.sell.payout");
  const fee = (type: CardType) => t("cardNote", { percent: config.card_fee_pct[type] });
  const options: Option[] = [
    {
      key: "balance",
      payout: { to: "balance" },
      name: t("balance"),
      note: t("balanceNote", { percent: config.balance_bonus_pct }),
      type: null,
    },
    ...cards.map((c) => ({
      key: c.id,
      payout: { to: "saved", cardId: c.id, type: c.type } as const, // keeps the literal types of the union, no widening
      name: `${CARD_BRANDS[c.type]} •••• ${c.last4}`,
      note: fee(c.type),
      type: c.type,
    })),
    ...(cards.length < config.max_cards
      ? CARD_TYPES.map((type) => ({
          key: `new-${type}`,
          payout: {
            to: "new",
            type,
            digits: value.to === "new" && value.type === type ? value.digits : "",
          } as const, // keeps the literal types of the union, no widening
          name: `${t("newCard")} ${CARD_BRANDS[type]}`,
          note: fee(type),
          type,
        }))
      : []),
  ];
  return (
    <fieldset>
      <legend className="text-fg-muted mb-2 text-sm font-semibold">{t("title")}</legend>
      <div role="radiogroup" className="grid grid-cols-2 gap-2">
        {options.map((o) => {
          const on = same(o.payout, value);
          return (
            <button
              key={o.key}
              type="button"
              role="radio"
              aria-checked={on}
              aria-label={`${o.name}. ${o.note}`}
              onClick={() => {
                onPick(o.payout);
              }}
              className={cn(
                "flex flex-col items-start gap-2 rounded-lg border-2 p-2.5 text-left transition-colors",
                "focus-visible:ring-accent focus-visible:outline-none focus-visible:ring-2",
                on
                  ? "border-accent bg-accent/10"
                  : "border-border bg-surface-2 hover:border-border-strong",
                o.type === null && "col-span-2 flex-row items-center",
              )}
            >
              {o.type === null ? (
                <span className="bg-bg grid size-10 shrink-0 place-items-center rounded-lg">
                  <LogoMark className="text-accent size-6" />
                </span>
              ) : (
                // eslint-disable-next-line @next/next/no-img-element -- static brand logos from /public
                <img
                  src={CARD_LOGOS[o.type]}
                  alt=""
                  width={60}
                  height={36}
                  className="h-9 w-auto rounded"
                />
              )}
              <span className="min-w-0">
                <span className="block text-sm font-semibold">{o.name}</span>
                <span
                  className={cn("block text-xs", o.type === null ? "text-accent" : "text-fg-dim")}
                >
                  {o.note}
                </span>
              </span>
            </button>
          );
        })}
      </div>
      {cards.length >= config.max_cards ? (
        <p className="text-fg-dim mt-2 text-xs">{t("cardsLimit", { count: config.max_cards })}</p>
      ) : null}
    </fieldset>
  );
}
