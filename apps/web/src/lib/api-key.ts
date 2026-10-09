/**
 * The API key on the profile: wire shapes and calls for `/api/v1/me/api-key`.
 *
 * The token is shown once, when it is issued; the server keeps only its hash. Nothing here
 * stores it — the caller holds it in state until the buyer says «Готово».
 */
import { SessionApiError } from "@csmarket/api-client";

import { session } from "./api";

export type PricingProfile = "retail" | "cost";

/** `ApiKeyOut`: the live key, never its token. */
export interface ApiKeyOut {
  id: string;
  pricing_profile: PricingProfile;
  created_at: string;
  last_used_at: string | null;
}

/** `ApiKeyIssuedOut`: a new key with its token, the only time it is told. */
export interface ApiKeyIssuedOut {
  id: string;
  token: string;
  pricing_profile: PricingProfile;
  created_at: string;
}

export const API_KEY_KEY = ["api-key"] as const;

/** A key needs a booked top-up or the USD wallet; neither is there yet. */
export class ApiKeyNotAllowedError extends Error {
  constructor() {
    super("api key not allowed");
    this.name = "ApiKeyNotAllowedError";
  }
}

/** `GET /me/api-key`: the live key, or `null` when there is none. */
export function getApiKey(): Promise<ApiKeyOut | null> {
  return session.apiGet<ApiKeyOut | null>("/api/v1/me/api-key");
}

/** `POST /me/api-key`: issue a key, revoking the live one (the tariff carries over). */
export async function issueApiKey(key: string): Promise<ApiKeyIssuedOut> {
  try {
    return await session.apiPost<ApiKeyIssuedOut>(
      "/api/v1/me/api-key",
      {},
      { idempotencyKey: key },
    );
  } catch (err) {
    if (
      err instanceof SessionApiError &&
      err.status === 409 &&
      err.code === "api_key_not_allowed"
    ) {
      throw new ApiKeyNotAllowedError();
    }
    throw err;
  }
}

/** `DELETE /me/api-key` (204): the key stops working at once. */
export function revokeApiKey(key: string): Promise<undefined> {
  return session.api<undefined>("/api/v1/me/api-key", { method: "DELETE", idempotencyKey: key });
}

/** A fresh `POST` / `DELETE /me/api-key` key. */
export function mintApiKeyKey(): string {
  return `web-apikey-${crypto.randomUUID()}`;
}
