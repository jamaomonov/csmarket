"use client";

import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { TradeSteps, type TradeStep } from "@/components/trades/TradeSteps";
import { listOrders } from "@/lib/orders";

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

/**
 * Is the buyer still before their first skin? A guest is; a signed-in buyer is while none of
 * their newest orders was received. `null` while it is not known yet (nothing is shown).
 */
export function useFirstPurchase(signedIn: boolean): boolean | null {
  const orders = useQuery({
    queryKey: ["orders", "first-page"],
    queryFn: () => listOrders(),
    enabled: signedIn,
    staleTime: 5 * 60_000,
  });
  if (!signedIn) return true;
  if (orders.isError) return false;
  if (!orders.data) return null;
  return !orders.data.items.some((o) => o.status === "delivered");
}
