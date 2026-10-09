import { ArrowLeftRight, Gift, HandCoins, ReceiptText, Star, Store, User } from "lucide-react";

import type { ComponentType } from "react";

import { SteamIcon } from "@/components/icons/SteamIcon";
import {
  ACCOUNT,
  MARKET,
  REFERRAL,
  REVIEWS,
  SELL,
  STEAM_TOPUP,
  TRADES,
  TRANSACTIONS,
} from "@/lib/paths";

/** A lucide icon or one of ours (`SteamIcon`): sized and coloured by `className`. */
export type NavIcon = ComponentType<{ className?: string; "aria-hidden"?: boolean }>;

export interface NavEntry {
  /** The key under `web.nav`. */
  key:
    | "sell"
    | "market"
    | "steamTopup"
    | "reviews"
    | "profile"
    | "transactions"
    | "trades"
    | "referral";
  href: string;
  icon: NavIcon;
}

/** The header's sections, in order. */
export const MAIN_NAV: NavEntry[] = [
  { key: "sell", href: SELL, icon: HandCoins },
  { key: "market", href: MARKET, icon: Store },
  { key: "steamTopup", href: STEAM_TOPUP, icon: SteamIcon },
  { key: "reviews", href: REVIEWS, icon: Star },
];

/** The account menu (before «Выйти»). */
export const ACCOUNT_NAV: NavEntry[] = [
  { key: "profile", href: ACCOUNT, icon: User },
  { key: "transactions", href: TRANSACTIONS, icon: ReceiptText },
  { key: "trades", href: TRADES, icon: ArrowLeftRight },
  { key: "referral", href: REFERRAL, icon: Gift },
];

/** «Обмены» is the list and every order and sale page it opens. */
const TRADE_PATHS = ["/orders", "/account/sales"];

/** The market is the catalogue and everything under it. */
const MARKET_PATHS = ["/category", "/weapon", "/item"];

/** Whether the nav entry is the section the visitor is in. */
export function isCurrent(entry: NavEntry, pathname: string): boolean {
  if (entry.href === MARKET) {
    return (
      pathname === MARKET || [MARKET, ...MARKET_PATHS].some((p) => pathname.startsWith(`${p}/`))
    );
  }
  if (entry.href === TRADES && TRADE_PATHS.some((p) => pathname.startsWith(`${p}/`))) return true;
  return pathname === entry.href || pathname.startsWith(`${entry.href}/`);
}
