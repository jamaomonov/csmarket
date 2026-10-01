"use client";

import { createContext, useContext, useEffect, useMemo, useState } from "react";

import type { SkinListing } from "@csmarket/utils/skins";
import type { ReactNode } from "react";

import { fetchSkinListings } from "@/lib/skins";

interface OffersState {
  /** `null` while loading; `[]` when there are none or the read failed. */
  offers: SkinListing[] | null;
  /** The lowest-priced offer — what the picture and the headline price show. */
  cheapest: SkinListing | null;
}

const OffersContext = createContext<OffersState>({ offers: null, cheapest: null });

/**
 * Loads an item's live offers once, in the browser, for every reader: the headline price
 * (the cheapest offer is the price someone can pay), the picture (its float, stickers and
 * inspect link) and the offers list. A page render never waits on it — the listings read
 * is the one catalogue call that can reach Waxpeer.
 */
export function SkinOffersProvider({ slug, children }: { slug: string; children: ReactNode }) {
  const [offers, setOffers] = useState<SkinListing[] | null>(null);
  useEffect(() => {
    const ctl = new AbortController();
    setOffers(null);
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
  const value = useMemo<OffersState>(
    () => ({
      offers,
      cheapest:
        offers && offers.length > 0
          ? offers.reduce((a, b) => (Number(b.price_usd) < Number(a.price_usd) ? b : a))
          : null,
    }),
    [offers],
  );
  return <OffersContext.Provider value={value}>{children}</OffersContext.Provider>;
}

export function useSkinOffers(): SkinListing[] | null {
  return useContext(OffersContext).offers;
}

/** The cheapest live offer, `null` until offers load or when there are none. */
export function useCheapestOffer(): SkinListing | null {
  return useContext(OffersContext).cheapest;
}
