"use client";

import { cn } from "@csmarket/ui";
import { CreditCard, Wallet } from "lucide-react";

import type { Provider } from "@/lib/balance";
import type { ReactNode } from "react";

import { WALLET } from "@/lib/prefer-balance";

/** Kassa brand names: never translated. The dev `mock` kassa reads as a test payment. */
const KASSA_NAMES: Readonly<Record<string, string>> = {
  click: "Click",
  payme: "Payme",
  uzum: "Uzum",
};

/** The kassas' app icons (`public/pay/`, the landing's too); the dev `mock` kassa has none. */
const KASSA_ICONS: Readonly<Record<string, string>> = {
  click: "/pay/click.png",
  payme: "/pay/payme.png",
  uzum: "/pay/uzum.png",
};

/** A kassa's fee percent in the visitor's locale: «1,5 %». */
function percent(pct: string, locale: string): string {
  return new Intl.NumberFormat(locale, { style: "percent", maximumFractionDigits: 2 }).format(
    Number(pct) / 100,
  );
}

function kassaIcon(slug: string): string | null {
  return KASSA_ICONS[slug] ?? null;
}

/** The tile's name for a kassa slug; `null` for one this storefront does not offer. */
export function kassaLabel(slug: string, testLabel: string, p2pLabel = ""): string | null {
  if (slug === "p2p") return p2pLabel;
  return slug === "mock" ? testLabel : (KASSA_NAMES[slug] ?? null);
}

/** The kassas worth a tile, in the API's order. */
export function offeredKassas(
  providers: readonly Provider[] | undefined,
  forTopup = false,
): Provider[] {
  return (providers ?? []).filter(
    (p) => kassaLabel(p.slug, "") !== null && (forTopup || p.topup_only !== true),
  );
}

/** A tile that can be paid through now (not under maintenance). */
export function isOpen(p: Provider): boolean {
  return p.status !== "maintenance";
}

/** The first kassa that can be paid through — the default choice. */
export function firstOpen(offered: readonly Provider[]): string | null {
  return offered.find(isOpen)?.slug ?? null;
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
  labels: { legend: string; test: string; none: string; maintenance: string; p2p?: string };
  wallet?: WalletOption;
  /** `lg`: big tiles, three to a row (the deposit page). Default `md`. */
  size?: "md" | "lg";
  /** Formats a kassa's percent («1,5 %»). */
  locale: string;
  /** The deposit page: offer the top-up-only kassas (P2P) too. */
  forTopup?: boolean;
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
  locale,
  forTopup = false,
}: PaymentPickerProps) {
  const offered = offeredKassas(providers, forTopup);
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
                    "text-small block font-normal tabular-nums",
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
              disabled={!isOpen(p)}
              onClick={() => {
                onPick(p.slug);
              }}
              className={cn(
                TILE,
                "flex items-center justify-center gap-2 disabled:cursor-not-allowed disabled:opacity-50",
                size === "lg" ? "h-20 gap-3 rounded-lg text-lg font-bold" : "h-12",
                tileState(p.slug === method && isOpen(p)),
              )}
            >
              {p.slug === "p2p" && (
                <CreditCard
                  className={size === "lg" ? "text-accent size-8" : "text-accent size-6"}
                  aria-hidden
                />
              )}
              {kassaIcon(p.slug) !== null && (
                // eslint-disable-next-line @next/next/no-img-element -- static brand logos from /public
                <img
                  src={kassaIcon(p.slug) ?? ""}
                  alt=""
                  width={size === "lg" ? 32 : 24}
                  height={size === "lg" ? 32 : 24}
                  className={size === "lg" ? "rounded-lg" : "rounded-md"}
                />
              )}
              <span className="flex flex-col items-start leading-tight">
                {kassaLabel(p.slug, labels.test, labels.p2p)}
                {!isOpen(p) ? (
                  <span className="text-fg-muted text-label font-normal">{labels.maintenance}</span>
                ) : (
                  Number(p.fee_pct) > 0 && (
                    <span className="text-fg-dim text-label font-normal">
                      {percent(p.fee_pct, locale)}
                    </span>
                  )
                )}
              </span>
            </button>
          ))}
        </div>
      )}
    </fieldset>
  );
}
