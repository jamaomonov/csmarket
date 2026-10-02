"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import type { Me } from "@/lib/auth";
import type { CheckState } from "@/lib/trade-link";

import { session } from "@/lib/api";

interface CheckOut extends CheckState {
  trade_link: string | null;
}

export interface TradeLinkGate {
  /** The saved link, `null` when there is none (or nobody is signed in). */
  link: string | null;
  /** The advisory check is running. */
  checking: boolean;
  /** The latest verdict on `link`: this page's own check or refusal, else the stored one. */
  state: CheckState;
  /** The checkout refused the link: hold that verdict until the profile says otherwise. */
  refuse: (state: CheckState) => void;
}

/**
 * The buyer's trade link, as the buy panel needs it. A link never checked (or whose last
 * check could not reach Steam) is checked once on mount — advisory: an `unavailable`
 * answer still lets the buyer pay, as the checkout does.
 */
export function useTradeLinkGate(user: Me | null, refreshMe: () => Promise<void>): TradeLinkGate {
  const link = user?.trade_link ?? null;
  const storedVerdict = user?.trade_link_verdict ?? null;
  const storedReason = user?.trade_link_reason ?? null;
  const [own, setOwn] = useState<{ link: string; state: CheckState } | null>(null);
  const [checking, setChecking] = useState(false);
  // One check per link per mount: re-renders and a refreshed profile never start another.
  const started = useRef<string | null>(null);

  useEffect(() => {
    if (link === null || storedVerdict !== null || started.current === link) return;
    started.current = link;
    setChecking(true);
    session
      .apiPost<CheckOut>("/api/v1/me/trade-link/check", {})
      .then((out) => {
        setOwn({ link, state: { verdict: out.verdict, reason: out.reason } });
      })
      .catch(() => {
        setOwn({ link, state: { verdict: null, reason: "unavailable" } });
      })
      .finally(() => {
        setChecking(false);
        void refreshMe();
      });
  }, [link, storedVerdict, refreshMe]);

  const refuse = useCallback(
    (state: CheckState) => {
      if (link !== null) setOwn({ link, state });
    },
    [link],
  );

  const state =
    own !== null && own.link === link
      ? own.state
      : { verdict: storedVerdict, reason: storedReason };
  return { link, checking, state, refuse };
}
