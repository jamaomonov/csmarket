/**
 * Orders: wire shapes and calls for `/api/v1/orders*`, `/api/v1/me/orders` and the
 * dev-only `/api/v1/dev/orders/{number}/{pay,trade}`.
 *
 * The 409s the buy panel acts on are turned into typed errors; anything else (an outage,
 * a rate limit, a code this client does not know) is rethrown as it came, and the caller
 * shows its own generic copy — never the API's text.
 */
import { SessionApiError } from "@csmarket/api-client";

import { session } from "./api";

import type { Locale } from "@csmarket/i18n";

export type OrderStatus =
  "pending" | "paid" | "buying" | "trade_sent" | "delivered" | "cancelled" | "failed" | "returned";

export type TradeState = "buying" | "offer_sent" | "accepted" | "released" | "failed";

export type TradeReason =
  "not_accepted" | "sold_out" | "try_later" | "trade_link" | "support" | "other";

/** `SkinSellerOut`: who sends the trade, as Steam shows them. */
export interface SkinSellerOut {
  name: string | null;
  avatar_url: string | null;
  level: number | null;
  joined_at: string | null;
}

/** `SkinTradeOut`: the buyer's view of the trade. */
export interface SkinTradeOut {
  state: TradeState;
  reason_code: TradeReason | null;
  /** The Steam trade offer, once sent. */
  offer_url: string | null;
  send_until: string | null;
  release_date: string | null;
  seller: SkinSellerOut | null;
  refunded_to: "balance" | null;
}

/** `OrderOut`. Amounts are strings: whole soʻm, USD with six decimals. */
export interface OrderOut {
  number: string;
  /** An unpaid order past `expires_at` already reads `cancelled`. */
  status: OrderStatus;
  slug: string;
  /** `market_hash_name`; skin names stay English. */
  name: string;
  phase: string | null;
  image_url: string | null;
  /** Catalogue wear code (`FN`…`BS`); `null` for items without wear. */
  exterior: string | null;
  /** Catalogue rarity colour, `#rrggbb`. */
  rarity_color: string | null;
  /** The bought offer's float, e.g. `"0.6214"`; `null` on older orders. */
  float_value: string | null;
  /** The bought offer's pattern (paint seed). */
  paint_seed: number | null;
  price_uzs: string;
  price_usd: string;
  created_at: string;
  expires_at: string;
  paid_at: string | null;
  delivered_at: string | null;
  paid_with: string | null;
  refunded_to: "balance" | null;
  /** The order can still be paid (`status === "pending"`). */
  payable: boolean;
  /** `api`: bought over the public API from the USD wallet (`price_uzs` is `"0"`). */
  channel: "site" | "api";
  trade: SkinTradeOut | null;
}

/** `OrdersPage`: newest first; `next_cursor` is `null` on the last page. */
export interface OrdersPage {
  items: OrderOut[];
  next_cursor: string | null;
}

export type PayProvider = "wallet" | "click" | "payme" | "uzum" | "mock";

export interface CreateOrderBody {
  slug: string;
  listing_id: string;
  /** Whole soʻm the buyer saw, a JSON integer. */
  price_uzs: number;
}

export interface PayOrderBody {
  provider: PayProvider;
  locale: Locale;
}

/** `OrderPayOut`. Navigation never reads `order` here: the order page re-reads it. */
export interface OrderPayOut {
  order: OrderOut;
  /** The kassa's page; `null` for the balance. */
  intent_url: string | null;
}

export interface NextOffer {
  listing_id: string;
  price_uzs: string;
}

export type TradeLinkCode = "trade_link_missing" | "trade_link_bad";
export type TradeLinkReason = "invalid" | "private" | "trade_ban" | "hold";

/** The offer's price moved past the tolerance; `priceUzs` is the server's new price. */
export class PriceChangedError extends Error {
  constructor(public readonly priceUzs: string) {
    super("price changed");
    this.name = "PriceChangedError";
  }
}

/** The offer was sold; `nextOffer` is the cheapest one left, if any. */
export class OfferGoneError extends Error {
  constructor(public readonly nextOffer: NextOffer | null) {
    super("offer gone");
    this.name = "OfferGoneError";
  }
}

/** No trade link (`reason` null), or one the last check found bad. */
export class TradeLinkError extends Error {
  constructor(
    public readonly code: TradeLinkCode,
    public readonly reason: TradeLinkReason | null,
  ) {
    super("trade link refused");
    this.name = "TradeLinkError";
  }
}

export class BalanceTooLowError extends Error {
  constructor() {
    super("balance too low");
    this.name = "BalanceTooLowError";
  }
}

/** The order is no longer `pending`: `reason` is `paid` or `expired`. */
export class OrderNotPayableError extends Error {
  constructor(public readonly reason: string) {
    super("order not payable");
    this.name = "OrderNotPayableError";
  }
}

export class BuyingDisabledError extends Error {
  constructor() {
    super("buying disabled");
    this.name = "BuyingDisabledError";
  }
}

const TRADE_LINK_REASONS: ReadonlySet<string> = new Set([
  "invalid",
  "private",
  "trade_ban",
  "hold",
]);

/** The problem+json body's fields, when it is one. */
function problem(err: SessionApiError): Record<string, unknown> {
  const body = err.body;
  // Narrowing an unknown JSON body to the object shape we read field by field.
  return typeof body === "object" && body !== null ? (body as Record<string, unknown>) : {};
}

function nextOfferOf(raw: unknown): NextOffer | null {
  if (typeof raw !== "object" || raw === null) return null;
  // Trusted server JSON, narrowed field by field below.
  const o = raw as Record<string, unknown>;
  return typeof o.listing_id === "string" && typeof o.price_uzs === "string"
    ? { listing_id: o.listing_id, price_uzs: o.price_uzs }
    : null;
}

/** The 409s of `POST /orders` and `POST /orders/{number}/pay` → typed errors. */
function orderError(err: unknown): unknown {
  if (!(err instanceof SessionApiError) || err.status !== 409) return err;
  const p = problem(err);
  switch (err.code ?? "") {
    case "price_changed":
      return typeof p.price_uzs === "string" ? new PriceChangedError(p.price_uzs) : err;
    case "offer_gone":
      return new OfferGoneError(nextOfferOf(p.next_offer));
    case "trade_link_missing":
      return new TradeLinkError("trade_link_missing", null);
    case "trade_link_bad":
      return new TradeLinkError(
        "trade_link_bad",
        typeof p.reason === "string" && TRADE_LINK_REASONS.has(p.reason)
          ? // Narrowed by the set above.
            (p.reason as TradeLinkReason)
          : "invalid",
      );
    case "balance_too_low":
      return new BalanceTooLowError();
    case "order_not_payable":
      return new OrderNotPayableError(typeof p.reason === "string" ? p.reason : "expired");
    case "buying_disabled":
      return new BuyingDisabledError();
    default:
      return err;
  }
}

/**
 * `POST /orders`: open an order for one offer at the price the buyer saw (201), or the
 * order this key already opened (200, whatever the body says). The key is the caller's
 * (see `orderKeyFor`), kept across retries of the same purchase.
 */
export async function createOrder(body: CreateOrderBody, key: string): Promise<OrderOut> {
  try {
    return await session.apiPost<OrderOut>("/api/v1/orders", body, { idempotencyKey: key });
  } catch (err) {
    throw orderError(err);
  }
}

/** `POST /orders/{number}/pay`: from the balance at once, or a kassa page to open. */
export async function payOrder(
  number: string,
  body: PayOrderBody,
  key: string,
): Promise<OrderPayOut> {
  try {
    return await session.apiPost<OrderPayOut>(
      `/api/v1/orders/${encodeURIComponent(number)}/pay`,
      body,
      { idempotencyKey: key },
    );
  } catch (err) {
    throw orderError(err);
  }
}

/** `GET /orders/{number}`: the caller's order (404 for anyone else's). */
export function getOrder(number: string): Promise<OrderOut> {
  return session.apiGet<OrderOut>(`/api/v1/orders/${encodeURIComponent(number)}`);
}

/** Query key of «Мои заказы», for whoever needs to invalidate it. */
export const ORDERS_KEY = ["orders", "list"] as const;

/** The query key of one order (its page; a socket nudge invalidates it). */
export const orderKey = (number: string) => ["orders", "order", number] as const;

/** `GET /me/orders`: one page, newest first; pass `next_cursor` back for the next. */
export function listOrders(cursor?: string): Promise<OrdersPage> {
  const query = cursor ? `?cursor=${encodeURIComponent(cursor)}` : "";
  return session.apiGet<OrdersPage>(`/api/v1/me/orders${query}`);
}

/**
 * Dev only (404 in prod): settle the order through the test kassa. A repeat is a no-op;
 * an order that expired meanwhile is `OrderNotPayableError`.
 */
export async function devPayOrder(number: string): Promise<OrderOut> {
  try {
    return await session.apiPost<OrderOut>(
      `/api/v1/dev/orders/${encodeURIComponent(number)}/pay`,
      {},
    );
  } catch (err) {
    throw orderError(err);
  }
}

export type DevTradeAction = "accept" | "decline" | "rollback";

/** Dev only (404 in prod): move the order's trade in the dev stack. The order follows. */
export async function devTrade(number: string, action: DevTradeAction): Promise<void> {
  await session.apiPost(`/api/v1/dev/orders/${encodeURIComponent(number)}/trade`, {
    action,
  });
}

/**
 * Where a purchase goes next: its order page, and whether this call opened the payment
 * (`false` for a replayed order that was already paid). `null`: retry with a new order key.
 */
export type PlaceOutcome = { number: string; opened: boolean } | null;

/**
 * Create (or replay) the order, then pay it with a fresh pay key.
 *
 * A replayed order that expired (`cancelled`, or `order_not_payable` / `expired` on pay)
 * answers `null`: the caller retries once with a new order key. A replayed order that is
 * already paid answers its number — the purchase went through, and a new order would buy
 * the skin twice. The pay answer itself is not read: the order page re-reads the order.
 */
export async function createAndPay(
  body: CreateOrderBody,
  pay: PayOrderBody,
  orderKey: string,
  payKey: () => string,
): Promise<PlaceOutcome> {
  const order = await createOrder(body, orderKey);
  if (order.status === "cancelled") return null;
  if (!order.payable) return { number: order.number, opened: false };
  try {
    await payOrder(order.number, pay, payKey());
  } catch (err) {
    if (err instanceof OrderNotPayableError) {
      return err.reason === "paid" ? { number: order.number, opened: false } : null;
    }
    throw err;
  }
  return { number: order.number, opened: true };
}

const PROVIDERS: ReadonlySet<string> = new Set(["wallet", "click", "payme", "uzum", "mock"]);

/** A method slug the pay route takes. */
export function isPayProvider(slug: string): slug is PayProvider {
  return PROVIDERS.has(slug);
}
