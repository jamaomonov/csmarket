"use client";

import { cn } from "@csmarket/ui";
import { Wallet } from "lucide-react";

import type { Provider } from "@/lib/balance";
import type { ReactNode } from "react";

import { WALLET } from "@/lib/prefer-balance";

/** Kassa brand names: never translated. The dev `mock` kassa reads as a test payment. */
const KASSA_NAMES: Readonly<Record<string, string>> = {
  click: "Click",
  payme: "Payme",
  uzum: "Uzum",
};

/** The tile's name for a kassa slug; `null` for one this storefront does not offer. */
export function kassaLabel(slug: string, testLabel: string): string | null {
  return slug === "mock" ? testLabel : (KASSA_NAMES[slug] ?? null);
}

/** The kassas worth a tile, in the API's order. */
export function offeredKassas(providers: readonly Provider[] | undefined): Provider[] {
  return (providers ?? []).filter((p) => kassaLabel(p.slug, "") !== null);
}

/** The balance as a payment method (the buy panel's; top-ups have none). */
export interface WalletOption {
  label: string;
  /** Under the label: the balance, or what is missing; `null` while it loads. */
  detail: string | null;
  /** The balance covers the price: the tile can be picked. */
  covers: boolean;
  /** Beside a short balance: where to top it up. */
  action?: ReactNode;
}

export interface PaymentPickerProps {
  /** The kassas open now; `undefined` while the list loads. */
  providers: readonly Provider[] | undefined;
  /** The selected method — a kassa slug or `wallet` — or `null` for none. */
  method: string | null;
  onPick: (method: string) => void;
  labels: { legend: string; test: string; none: string };
  wallet?: WalletOption;
  /** `lg`: big tiles, three to a row (the deposit page). Default `md`. */
  size?: "md" | "lg";
}

const TILE = "rounded-md border px-3 text-sm font-semibold";
const tileState = (on: boolean): string =>
  on ? "border-accent bg-accent/10" : "border-border bg-surface hover:border-border-strong";

/** Payment method tiles: the balance (when given), then the kassas open now. */
export function PaymentPicker({
  providers,
  method,
  onPick,
  labels,
  wallet,
  size = "md",
}: PaymentPickerProps) {
  const offered = offeredKassas(providers);
  const noKassa = providers !== undefined && offered.length === 0;
  return (
    <fieldset>
      <legend className="text-fg-muted mb-2 text-sm font-semibold">{labels.legend}</legend>
      {wallet && (
        <div className="mb-2 flex items-center gap-3">
          <button
            type="button"
            aria-pressed={method === WALLET}
            disabled={!wallet.covers}
            onClick={() => {
              onPick(WALLET);
            }}
            className={cn(
              TILE,
              "flex min-h-12 flex-1 items-center gap-3 py-2 text-left disabled:cursor-not-allowed disabled:opacity-70",
              tileState(method === WALLET),
            )}
          >
            <Wallet className="text-accent h-5 w-5 shrink-0" aria-hidden />
            <span className="min-w-0">
              <span className="block">{wallet.label}</span>
              {wallet.detail === null ? (
                <span className="bg-surface-2 mt-1 block h-3 w-20 animate-pulse rounded" />
              ) : (
                <span
                  className={cn(
                    "block text-[13px] font-normal tabular-nums",
                    wallet.covers ? "text-fg-dim" : "text-danger",
                  )}
                >
                  {wallet.detail}
                </span>
              )}
            </span>
          </button>
          {wallet.action}
        </div>
      )}
      {providers === undefined ? (
        <div aria-busy className="bg-surface h-12 animate-pulse rounded-md" />
      ) : noKassa ? (
        wallet?.covers ? null : (
          <p className="text-fg-muted text-sm">{labels.none}</p>
        )
      ) : (
        <div
          className={cn(
            "grid grid-cols-2 gap-2",
            size === "lg" ? "sm:grid-cols-3 sm:gap-3" : "sm:grid-cols-4",
          )}
        >
          {offered.map((p) => (
            <button
              key={p.slug}
              type="button"
              aria-pressed={p.slug === method}
              onClick={() => {
                onPick(p.slug);
              }}
              className={cn(
                TILE,
                size === "lg" ? "h-20 rounded-lg text-lg font-bold" : "h-12",
                tileState(p.slug === method),
              )}
            >
              {kassaLabel(p.slug, labels.test)}
            </button>
          ))}
        </div>
      )}
    </fieldset>
  );
}
