/**
 * The customer's balance: wire shapes and calls for `/api/v1/wallet*`,
 * `/api/v1/payments/providers` and the dev-only `/api/v1/dev/topups/{number}/pay`.
 *
 * Amounts travel as strings of whole soʻm (`"50000"`; history entries are signed,
 * `"+50000"` / `"-10000"`). The bounds below only spare the customer a round trip:
 * the API is the authority and answers 422 `topup_amount` outside them.
 */
import { formatUzs } from "@csmarket/utils";

import { session } from "./api";

import type { Locale } from "@csmarket/i18n";

/** Smallest top-up, whole soʻm (owner decision D1). */
export const TOPUP_MIN = 1000;
/** Largest top-up, whole soʻm (owner decision D1). */
export const TOPUP_MAX = 10_000_000;
/** Round numbers a customer would actually transfer. */
export const QUICK_AMOUNTS: readonly number[] = [50_000, 100_000, 250_000, 500_000];

export type TopupStatus = "pending" | "succeeded" | "expired" | "reversed";

/** `TopupOut`. */
export interface Topup {
  /** `T…`, the number the customer and the kassa see. */
  number: string;
  amount_uzs: string;
  /** The kassa slug the top-up was opened in. */
  provider: string | null;
  status: TopupStatus;
  expires_at: string;
  /** Where to pay; `null` once the top-up cannot be paid (or for the dev `mock` kassa). */
  intent_url: string | null;
  /**
   * `pending` and a kassa holds an attempt: it may still settle after `expires_at`, so a
   * pending top-up without `intent_url` is being checked, not expired.
   */
  awaiting_kassa: boolean;
}

export type EntryKind =
  | "topup"
  | "topup_reversal"
  | "admin_adjust"
  | "purchase"
  | "refund"
  | "sale_credit"
  | "payout_return"
  | "fx_convert"
  | "admin_adjust_usd";

/** `EntryOut`: one line of the balance history. */
export interface Entry {
  id: string;
  kind: EntryKind;
  /** Signed whole soʻm: `"+50000"` credited, `"-10000"` debited. */
  amount_uzs: string;
  created_at: string;
  /** The top-up's number for `topup` / `topup_reversal`, the sale's for `sale_credit` /
   * `payout_return`; else `null`. */
  reference_number: string | null;
  /** Which wallet the line belongs to. */
  currency: "UZS" | "USD";
  /** Dollars for a USD line, else `null`. */
  amount_usd: string | null;
}

/** `EntriesOut`: newest first; `next_cursor` is `null` on the last page. */
export interface EntriesPage {
  items: Entry[];
  next_cursor: string | null;
}

/** `ProviderOut`: a kassa the storefront may offer (`click`, `payme`, `uzum`, dev `mock`). */
export interface Provider {
  slug: string;
}

/** `UsdWalletOut`: the USD wallet, present once an admin switched it on. */
export interface UsdWallet {
  /** Dollars, three decimals (`"7.826"`). */
  balance_usd: string;
  /** soʻm per dollar; `null` while the rate is unavailable. */
  rate_uzs: string | null;
}

export interface Balance {
  balance_uzs: string;
  /** `null` unless the USD wallet is switched on for the customer. */
  usd: UsdWallet | null;
}

/** `ConvertOut`: the result of `POST /wallet/convert`. */
export interface ConvertOut {
  amount_uzs: string;
  amount_usd: string;
  rate_uzs: string;
  balance_uzs: string;
  balance_usd: string;
}

/** Smallest conversion, whole soʻm. */
export const CONVERT_MIN = 1000;
/** Largest conversion, whole soʻm. */
export const CONVERT_MAX = 100_000_000;

/**
 * Display-only dollars for `amountUzs` at `rate` (`"12777.01"`): floor to three decimals.
 * The server decides the real figure. `null` when the rate is unusable.
 */
export function previewUsd(amountUzs: number, rate: string): string | null {
  const m = /^(\d+)(?:\.(\d{1,2}))?$/.exec(rate);
  if (!m) return null;
  const cents = BigInt(m[1] ?? "0") * 100n + BigInt((m[2] ?? "").padEnd(2, "0"));
  if (cents === 0n) return null;
  const milli = (BigInt(Math.trunc(amountUzs)) * 1000n * 100n) / cents;
  const whole = milli / 1000n;
  return `${whole.toString()}.${(milli % 1000n).toString().padStart(3, "0")}`;
}

/** `POST /wallet/convert`: move soʻm into the USD wallet. The key is the caller's, one per form. */
export function convertToUsd(amountUzs: number, idempotencyKey: string): Promise<ConvertOut> {
  return session.apiPost<ConvertOut>(
    "/api/v1/wallet/convert",
    { amount_uzs: amountUzs },
    { idempotencyKey },
  );
}

export interface TopupRequest {
  /** Whole soʻm, a JSON integer. */
  amount_uzs: number;
  provider: string;
  /** Language of the kassa's page and of the page the customer returns to. */
  locale: Locale;
}

/** Where `topupAttemptKey` keeps the key between renders (a React ref fits). */
export interface AttemptStore {
  current: { signature: string; key: string } | null;
}

/** Query key of the balance, for the balance page and whoever needs to invalidate it. */
export const BALANCE_KEY = ["wallet", "balance"] as const;

/** `GET /wallet`: spendable soʻm, `"0"` before the first top-up. */
export function getBalance(): Promise<Balance> {
  return session.apiGet<Balance>("/api/v1/wallet");
}

/** The history filters `GET /wallet/entries?type=` knows. */
export type EntryType = "topup" | "withdrawal";

/** `GET /wallet/entries`: one page of history (of one `type` when given); pass `next_cursor`
 * back for the next. */
export function getEntries(cursor?: string, type?: EntryType): Promise<EntriesPage> {
  const params = new URLSearchParams();
  if (cursor) params.set("cursor", cursor);
  if (type) params.set("type", type);
  const query = params.size > 0 ? `?${params.toString()}` : "";
  return session.apiGet<EntriesPage>(`/api/v1/wallet/entries${query}`);
}

/** `GET /payments/providers`: the kassas open right now, in display order. Anonymous. */
export async function getProviders(): Promise<Provider[]> {
  const out = await session.apiGet<{ providers?: Provider[] }>("/api/v1/payments/providers", {
    anonymous: true,
  });
  return out.providers ?? [];
}

/**
 * `POST /wallet/topups`: open a top-up. The balance moves when the kassa settles, not here.
 *
 * The key is the caller's (see `topupAttemptKey`): a fresh key per call would make a
 * retry after a timeout open a second top-up instead of replaying the first.
 */
export function createTopup(body: TopupRequest, idempotencyKey: string): Promise<Topup> {
  return session.apiPost<Topup>("/api/v1/wallet/topups", body, { idempotencyKey });
}

/** `GET /wallet/topups/{number}`; `locale` picks the language of `intent_url`'s page. */
export function getTopup(number: string, locale?: Locale): Promise<Topup> {
  const query = locale ? `?locale=${locale}` : "";
  return session.apiGet<Topup>(`/api/v1/wallet/topups/${encodeURIComponent(number)}${query}`);
}

/**
 * `POST /dev/topups/{number}/pay`: settle a `mock` top-up. Dev only — the API answers
 * 404 in prod. Keyless on the API side: paying an already-paid top-up is a no-op.
 */
export function devPay(number: string): Promise<Topup> {
  return session.apiPost<Topup>(`/api/v1/dev/topups/${encodeURIComponent(number)}/pay`, {});
}

/**
 * One idempotency key per (amount, provider) the customer is asking for — the
 * `signature`, e.g. `"50000:click"`.
 *
 * Retrying the same request reuses the key, so the API replays the top-up it already
 * opened. Changing either part is a different request and mints a new key.
 */
export function topupAttemptKey(store: AttemptStore, signature: string): string {
  if (store.current?.signature !== signature) {
    store.current = { signature, key: `web-topup-${crypto.randomUUID()}` };
  }
  return store.current.key;
}

/** A signed wire amount (`"+50000"`, `"-10000"`) for display: `+50 000 сум`, `−10 000 сум`. */
export function signedUzs(locale: string, wire: string): string {
  const negative = wire.startsWith("-");
  const digits = wire.replace(/^[+-]/, "");
  return `${negative ? "−" : "+"}${formatUzs(locale, digits)}`;
}
