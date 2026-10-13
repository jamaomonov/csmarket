/**
 * Google Analytics 4: the measurement id and the funnel events. Only csmarket.uz sends
 * anything — a dev box, a preview or a test never reaches the property.
 *
 * Never put a person in an event: no Steam ID, user id, email, trade link or IP — only an
 * order or sale number, an amount in soʻm and a skin's English name (AGENTS.md §10).
 */

/** The property's web stream. Public by design: it ships in every page's HTML. */
export const GA_ID = "G-M6ZV9JK48X";

/** The only host whose visits are counted. */
export const GA_HOST = "csmarket.uz";

/** A paid order older than this is a revisit, not a purchase. */
const PURCHASE_WINDOW_MS = 60 * 60 * 1000;

const SENT_KEY = "csmarket.ga.purchases";

type Gtag = (command: "event", name: string, params?: Record<string, unknown>) => void;

declare global {
  interface Window {
    gtag?: Gtag;
  }
}

export function gaEnabled(host: string): boolean {
  return host === GA_HOST;
}

/** One GA4 item: the catalogue slug and the English market name. */
interface GaItem {
  item_id: string;
  item_name: string;
  price: number;
}

export type GaEvent =
  | { name: "login"; params: { method: "steam" } }
  | { name: "view_item"; params: { currency: "UZS"; value: number; items: GaItem[] } }
  | { name: "begin_checkout"; params: { currency: "UZS"; value: number; items: GaItem[] } }
  | { name: "add_payment_info"; params: { payment_type: string } }
  | {
      name: "purchase";
      params: { transaction_id: string; currency: "UZS"; value: number; items: GaItem[] };
    }
  | { name: "sell"; params: { transaction_id: string; currency: "UZS"; value: number } };

/** How long `track` waits for a tag that is still loading (it loads after interaction). */
const TAG_WAIT_TRIES = 10;
const TAG_WAIT_MS = 500;

/**
 * Sends one event once the tag is on the page. A page that never gets the tag (dev, a
 * blocker, tests) drops it after {@link TAG_WAIT_TRIES} tries.
 */
export function track(event: GaEvent, tries = TAG_WAIT_TRIES): void {
  if (typeof window === "undefined") return;
  if (window.gtag) {
    window.gtag("event", event.name, event.params);
  } else if (tries > 1 && gaEnabled(window.location.hostname)) {
    window.setTimeout(() => {
      track(event, tries - 1);
    }, TAG_WAIT_MS);
  }
}

export function gaItem(slug: string, name: string, priceUzs: string | number | null): GaItem {
  return { item_id: slug, item_name: name, price: Number(priceUzs ?? 0) };
}

/** Statuses an order reaches only after it was paid. */
const PAID = new Set(["paid", "buying", "trade_sent", "delivered", "returned"]);

interface PaidOrder {
  number: string;
  status: string;
  slug: string;
  name: string;
  price_uzs: string;
  paid_at: string | null;
}

/**
 * The `purchase` event for an order seen paid, once per order in this browser and only
 * within an hour of payment, so reopening an old order counts nothing.
 */
export function purchaseEvent(
  order: PaidOrder,
  now: number,
  sent: readonly string[],
): GaEvent | null {
  if (!PAID.has(order.status) || order.paid_at === null) return null;
  if (now - Date.parse(order.paid_at) > PURCHASE_WINDOW_MS) return null;
  if (sent.includes(order.number)) return null;
  const value = Number(order.price_uzs);
  return {
    name: "purchase",
    params: {
      transaction_id: order.number,
      currency: "UZS",
      value,
      items: [gaItem(order.slug, order.name, value)],
    },
  };
}

function readSent(): string[] {
  try {
    const raw = window.localStorage.getItem(SENT_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed.filter((n): n is string => typeof n === "string") : [];
  } catch {
    return [];
  }
}

/** Tracks a paid order's purchase once; remembers the last 50 numbers sent. */
export function trackPurchase(order: PaidOrder): void {
  if (typeof window === "undefined" || !gaEnabled(window.location.hostname)) return;
  const sent = readSent();
  const event = purchaseEvent(order, Date.now(), sent);
  if (event === null) return;
  track(event);
  try {
    window.localStorage.setItem(SENT_KEY, JSON.stringify([...sent, order.number].slice(-50)));
  } catch {
    // Storage blocked: GA4 still drops a repeated transaction_id.
  }
}
