"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import type { SkinListing } from "@csmarket/utils/skins";
import type { ReactNode } from "react";

import { fetchSkinListings } from "@/lib/skins";

interface OffersState {
  /** `null` while loading; `[]` when there are none or the read failed. */
  offers: SkinListing[] | null;
  /** The lowest-priced offer — what the picture and the headline price show. */
  cheapest: SkinListing | null;
  /** The offer the buy panel buys: the cheapest until the buyer picks another. */
  selected: SkinListing | null;
  select: (listingId: string) => void;
  /** The server quoted another soʻm price for this offer: show and send that one. */
  reprice: (listingId: string, priceUzs: string) => void;
  /** This offer was sold: take it off the page. */
  drop: (listingId: string) => void;
}

const noop = (): void => undefined;

const OffersContext = createContext<OffersState>({
  offers: null,
  cheapest: null,
  selected: null,
  select: noop,
  reprice: noop,
  drop: noop,
});

function cheapestOf(offers: readonly SkinListing[] | null): SkinListing | null {
  return offers && offers.length > 0
    ? offers.reduce((a, b) => (Number(b.price_usd) < Number(a.price_usd) ? b : a))
    : null;
}

/**
 * Loads an item's live offers once, in the browser, for every reader: the headline price
 * (the cheapest offer is the price someone can pay), the picture (its float, stickers and
 * inspect link), the offers list and the buy panel. A page render never waits on it — the
 * listings read is the one catalogue call that can reach the market.
 */
export function SkinOffersProvider({ slug, children }: { slug: string; children: ReactNode }) {
  const [offers, setOffers] = useState<SkinListing[] | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  useEffect(() => {
    const ctl = new AbortController();
    setOffers(null);
    setSelectedId(null);
    fetchSkinListings(slug, ctl.signal)
      .then((r) => {
        if (!ctl.signal.aborted) setOffers(r.items);
      })
      .catch(() => {
        if (!ctl.signal.aborted) setOffers([]);
      });
    return () => {
      ctl.abort();
    };
  }, [slug]);
  const reprice = useCallback((listingId: string, priceUzs: string) => {
    setOffers(
      (all) =>
        all?.map((o) => (o.listing_id === listingId ? { ...o, price_uzs: priceUzs } : o)) ?? null,
    );
  }, []);
  const drop = useCallback((listingId: string) => {
    setOffers((all) => all?.filter((o) => o.listing_id !== listingId) ?? null);
  }, []);
  const value = useMemo<OffersState>(() => {
    const cheapest = cheapestOf(offers);
    return {
      offers,
      cheapest,
      selected: offers?.find((o) => o.listing_id === selectedId) ?? cheapest,
      select: setSelectedId,
      reprice,
      drop,
    };
  }, [offers, selectedId, reprice, drop]);
  return <OffersContext.Provider value={value}>{children}</OffersContext.Provider>;
}

export function useSkinOffers(): SkinListing[] | null {
  return useContext(OffersContext).offers;
}

/** The cheapest live offer, `null` until offers load or when there are none. */
export function useCheapestOffer(): SkinListing | null {
  return useContext(OffersContext).cheapest;
}

/** The offer to buy and how to change it (a row's «Выбрать», the next offer, a new price). */
export function useSelectedOffer(): Omit<OffersState, "offers" | "cheapest"> {
  const { selected, select, reprice, drop } = useContext(OffersContext);
  return { selected, select, reprice, drop };
}
