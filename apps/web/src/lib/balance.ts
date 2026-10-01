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

export type EntryKind = "topup" | "topup_reversal" | "admin_adjust";

/** `EntryOut`: one line of the balance history. */
export interface Entry {
  id: string;
  kind: EntryKind;
  /** Signed whole soʻm: `"+50000"` credited, `"-10000"` debited. */
  amount_uzs: string;
  created_at: string;
  /** The top-up's number for `topup` / `topup_reversal`; else `null`. */
  reference_number: string | null;
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

export interface Balance {
  balance_uzs: string;
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

/** `GET /wallet`: spendable soʻm, `"0"` before the first top-up. */
export function getBalance(): Promise<Balance> {
  return session.apiGet<Balance>("/api/v1/wallet");
}

/** `GET /wallet/entries`: one page of history; pass `next_cursor` back for the next. */
export function getEntries(cursor?: string): Promise<EntriesPage> {
  const query = cursor ? `?cursor=${encodeURIComponent(cursor)}` : "";
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
