"use client";

import { useEffect, useRef, useSyncExternalStore } from "react";

import type { Locale } from "@csmarket/i18n";

import {
  AUTO_OPEN_BUDGET_MS,
  markOpened,
  searchWithoutGo,
  shouldAutoOpen,
} from "@/lib/kassa-redirect";
import { arrivalKassa } from "@/lib/order-arrival";
import { mintPayKey } from "@/lib/order-key";
import { payOrder, type OrderOut, type PayProvider } from "@/lib/orders";

// The address is read on render; nothing here changes it but `replaceState`, which only
// drops `go` (the kassa param stays), so there is nothing to subscribe to.
const noSubscription = (): (() => void) => () => undefined;
const clientSearch = (): string => window.location.search;
const serverSearch = (): string => "";

/** The kassa the buyer came to this order page for (`?via=` / `?mock=1`), or `null`. */
export function useArrivalKassa(): PayProvider | null {
  return arrivalKassa(useSyncExternalStore(noSubscription, clientSearch, serverSearch));
}

/** A kassa whose page the order page may open by itself: a real one, not the test kassa. */
const opensAPage = (kassa: PayProvider | null): kassa is PayProvider =>
  kassa !== null && kassa !== "mock" && kassa !== "wallet";

/**
 * Open the chosen kassa once when the page arrived with `?go=1`, and strip the flag.
 *
 * The first answer spends the flag whatever it says. Only an order that is still
 * `pending` and payable opens anything; the kassa's page comes from the pay route asked
 * again with the same kassa (it reuses the attempt the buy panel opened). An answer
 * that lands after `AUTO_OPEN_BUDGET_MS` opens nothing: the button is there.
 */
export function useKassaAutoOpen(
  number: string,
  order: OrderOut | undefined,
  kassa: PayProvider | null,
  locale: Locale,
): void {
  const latch = useRef(false);
  const arrivedAt = useRef<number | null>(null);
  // Cleared on unmount: a pay answer that lands after the buyer left opens nothing.
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    arrivedAt.current = Date.now();
    return () => {
      alive.current = false;
    };
  }, []);
  useEffect(() => {
    if (!order || latch.current) return;
    latch.current = true;
    const { pathname, search, hash } = window.location;
    const open = shouldAutoOpen(number, search);
    if (open) markOpened(number);
    const rest = searchWithoutGo(search);
    if (rest !== search) window.history.replaceState(null, "", `${pathname}${rest}${hash}`);
    const late = (): boolean =>
      Date.now() - (arrivedAt.current ?? Date.now()) > AUTO_OPEN_BUDGET_MS;
    if (!open || !order.payable || order.status !== "pending" || !opensAPage(kassa) || late()) {
      return;
    }
    payOrder(number, { provider: kassa, locale }, mintPayKey()).then(
      (out) => {
        if (alive.current && out.intent_url !== null && !late()) {
          window.location.assign(out.intent_url);
        }
      },
      () => {
        // Nothing opens; the page shows the method and the button.
      },
    );
  }, [number, order, kassa, locale]);
}
