/**
 * The kassa fee the buyer pays on top (spec 2026-10-14-kassa-fee), for display. The API
 * freezes the real one on the payment; this counts it the same way: `ceil(base × pct / 100)`
 * whole soʻm, in integers (the percent has at most two decimals).
 */

import type { Provider } from "@/lib/balance";

export function kassaFee(base: number, pct: string): number {
  const hundredths = Math.round(Number(pct) * 100);
  if (!Number.isFinite(hundredths) || hundredths <= 0) return 0;
  return Math.ceil((base * hundredths) / 10000);
}

/** What the chosen kassa adds to `base`. */
export interface KassaCharge {
  slug: string;
  fee: number;
  total: number;
}

/** The chosen method's charge; `null` for the balance, no choice or a kassa without a fee. */
export function kassaCharge(
  base: number,
  kassas: readonly Provider[] | undefined,
  method: string | null,
): KassaCharge | null {
  const kassa = kassas?.find((p) => p.slug === method);
  if (kassa === undefined) return null;
  const fee = kassaFee(base, kassa.fee_pct);
  return fee > 0 ? { slug: kassa.slug, fee, total: base + fee } : null;
}
