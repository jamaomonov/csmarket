"use client";

import { useTranslations } from "next-intl";

import { TradeSteps, type TradeStep } from "@/components/trades/TradeSteps";

/** Where the buyer is: 1 sign in, 2 a working trade link, 3 pay (then accept in Steam). */
export type BuyStage = 1 | 2 | 3;

const KEYS = ["signIn", "link", "pay", "accept"] as const;

/** The way to a skin as four steps, the one the buyer is on lit up. */
export function BuySteps({ stage }: { stage: BuyStage }) {
  const t = useTranslations("web.buy.steps");
  const steps: TradeStep[] = KEYS.map((key, i) => ({
    label: t(key),
    state: i + 1 < stage ? "done" : i + 1 === stage ? "now" : "todo",
  }));
  return (
    <div className="text-small" data-testid="buy-steps">
      <TradeSteps steps={steps} />
    </div>
  );
}
