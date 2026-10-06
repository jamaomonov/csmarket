"use client";

import { cn, LogoMark } from "@csmarket/ui";
import { useTranslations } from "next-intl";

import {
  BALANCE_BONUS_PERCENT,
  PAYOUT_METHODS,
  SELL_FEE_PERCENT,
  type PayoutMethod,
} from "@/lib/sell";

/** The card brands' logos (`public/payout/*.png`) and names, never translated. */
export const CARD_BRANDS: Readonly<Record<Exclude<PayoutMethod, "balance">, string>> = {
  uzcard: "Uzcard",
  humo: "Humo",
  "uzum-visa": "Uzum Visa",
};

interface PayoutPickerProps {
  method: PayoutMethod;
  onPick: (method: PayoutMethod) => void;
}

/** Where the money goes: the csmarket balance (a bonus) or a card (a fee). A radio group. */
export function PayoutPicker({ method, onPick }: PayoutPickerProps) {
  const t = useTranslations("web.sell.payout");
  return (
    <fieldset>
      <legend className="text-fg-muted mb-2 text-sm font-semibold">{t("title")}</legend>
      <div role="radiogroup" className="grid grid-cols-2 gap-2">
        {PAYOUT_METHODS.map((m) => {
          const on = m === method;
          const name = m === "balance" ? t("balance") : CARD_BRANDS[m];
          const note =
            m === "balance"
              ? t("balanceNote", { percent: BALANCE_BONUS_PERCENT })
              : t("cardNote", { percent: SELL_FEE_PERCENT });
          return (
            <button
              key={m}
              type="button"
              role="radio"
              aria-checked={on}
              aria-label={`${name}. ${note}`}
              onClick={() => {
                onPick(m);
              }}
              className={cn(
                "flex flex-col items-start gap-2 rounded-lg border-2 p-2.5 text-left transition-colors",
                "focus-visible:ring-accent focus-visible:outline-none focus-visible:ring-2",
                on
                  ? "border-accent bg-accent/10"
                  : "border-border bg-surface-2 hover:border-border-strong",
                m === "balance" && "col-span-2 flex-row items-center",
              )}
            >
              {m === "balance" ? (
                <span className="bg-bg grid size-10 shrink-0 place-items-center rounded-lg">
                  <LogoMark className="text-accent size-6" />
                </span>
              ) : (
                // eslint-disable-next-line @next/next/no-img-element -- static brand logos from /public
                <img
                  src={`/payout/${m}.png`}
                  alt=""
                  width={60}
                  height={36}
                  className="h-9 w-auto rounded"
                />
              )}
              <span className="min-w-0">
                <span className="block text-sm font-semibold">{name}</span>
                <span
                  className={cn("block text-xs", m === "balance" ? "text-accent" : "text-fg-dim")}
                >
                  {note}
                </span>
              </span>
            </button>
          );
        })}
      </div>
    </fieldset>
  );
}
