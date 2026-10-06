import {
  ArrowLeftRight,
  Gamepad2,
  Gift,
  HandCoins,
  ReceiptText,
  Star,
  Store,
  User,
} from "lucide-react";

import type { LucideIcon } from "lucide-react";

import {
  ACCOUNT,
  HOME,
  REFERRAL,
  REVIEWS,
  SELL,
  STEAM_TOPUP,
  TRADES,
  TRANSACTIONS,
} from "@/lib/paths";

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
  icon: LucideIcon;
}

/** The header's sections, in order. */
export const MAIN_NAV: NavEntry[] = [
  { key: "sell", href: SELL, icon: HandCoins },
  { key: "market", href: HOME, icon: Store },
  { key: "steamTopup", href: STEAM_TOPUP, icon: Gamepad2 },
  { key: "reviews", href: REVIEWS, icon: Star },
];

/** The account menu (before «Выйти»). */
export const ACCOUNT_NAV: NavEntry[] = [
  { key: "profile", href: ACCOUNT, icon: User },
  { key: "transactions", href: TRANSACTIONS, icon: ReceiptText },
  { key: "trades", href: TRADES, icon: ArrowLeftRight },
  { key: "referral", href: REFERRAL, icon: Gift },
];

/** The market is the catalogue and everything under it. */
const MARKET_PATHS = ["/category", "/weapon", "/item"];

/** Whether the nav entry is the section the visitor is in. */
export function isCurrent(entry: NavEntry, pathname: string): boolean {
  if (entry.href === HOME) {
    return pathname === HOME || MARKET_PATHS.some((p) => pathname.startsWith(`${p}/`));
  }
  return pathname === entry.href || pathname.startsWith(`${entry.href}/`);
}
