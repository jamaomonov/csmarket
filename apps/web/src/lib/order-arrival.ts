/**
 * How the buy panel hands an order to its page: `?go=1` (open the kassa once, see
 * `kassa-redirect.ts`) and `via=<kassa>`, the method the buyer picked — the page has
 * no other way to know it, and re-asking the pay route with the same kassa reuses the
 * payment attempt already open. The test kassa's own return address carries `mock=1`.
 */
import { isPayProvider, type PayProvider } from "./orders";
import { orderPath } from "./paths";
import { WALLET } from "./prefer-balance";

const VIA_PARAM = "via";

/** Where the buy panel sends the buyer: with the kassa to open, or (`wallet`/`null`) plain. */
export function orderArrivalPath(number: string, kassa: PayProvider | null): string {
  if (kassa === null || kassa === WALLET) return orderPath(number);
  return `${orderPath(number)}?go=1&${VIA_PARAM}=${encodeURIComponent(kassa)}`;
}

/** The kassa this page was reached for, or `null`. Never the balance. */
export function arrivalKassa(search: string): PayProvider | null {
  const params = new URLSearchParams(search);
  const via = params.get(VIA_PARAM) ?? "";
  if (via !== WALLET && isPayProvider(via)) return via;
  return params.get("mock") === "1" ? "mock" : null;
}
