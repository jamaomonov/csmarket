import { assertNever } from "@csmarket/utils";

import type { Me } from "./auth";

export const STEAM_TRADE_URL_PAGE =
  "https://steamcommunity.com/my/tradeoffers/privacy#trade_offer_access_url";

export interface CheckState {
  verdict: Me["trade_link_verdict"];
  reason: Me["trade_link_reason"];
}

export type Tone = "ok" | "warn" | "bad" | "muted";

/**
 * Copy key under `web.account.tradeLink.status`, or null when nothing is worth saying.
 *
 * Keys off `verdict` and `reason` only: a stale `checked_at` never means "verified".
 */
export function verdictMessage(state: CheckState): { tone: Tone; key: string } | null {
  switch (state.verdict) {
    case "ok":
      return { tone: "ok", key: "ok" };
    case "warn":
      return { tone: "warn", key: "hold" };
    case "bad":
      return {
        tone: "bad",
        key: state.reason === "private" || state.reason === "trade_ban" ? state.reason : "invalid",
      };
    case null:
      return state.reason === "unavailable" ? { tone: "muted", key: "unavailable" } : null;
    default:
      return assertNever(state.verdict);
  }
}

const KNOWN = new Set(["trade_link_invalid", "trade_link_not_yours"]);

/** Copy key under `web.account.tradeLink.errors`. */
export function errorKey(code: string | undefined): string {
  return code && KNOWN.has(code) ? code : "generic";
}
