"use client";

import { Button } from "@csmarket/ui";
import { useTranslations } from "next-intl";

import type { Me } from "@/lib/auth";

import { TradeLinkForm } from "@/components/account/TradeLinkForm";
import { sellError } from "@/lib/sell";

interface InventoryRefusalProps {
  /** Why `GET /sell/inventory` failed. */
  error: unknown;
  user: Me;
  onRetry: () => void;
  /** The trade link was saved or checked again: read the inventory once more. */
  onLinkChange: () => void;
}

/** The stored trade-link verdict's reason → the `web.sell.steam` sentence that explains it. */
const LINK_REASONS: Readonly<Record<string, string>> = {
  hold: "hold",
  invalid: "trade_link_invalid",
  private: "profile_private",
  trade_ban: "trade_banned",
};

/** An inventory that could not be read: what is wrong, and the one action that can help. */
export function InventoryRefusal({ error, user, onRetry, onLinkChange }: InventoryRefusalProps) {
  const t = useTranslations("web.sell");
  const refusal = sellError(error);
  const code = refusal?.code;
  const steam = (reason: string | null | undefined): string =>
    reason && t.has(`steam.${reason}`) ? t(`steam.${reason}`) : t("steam.other");

  if (code === "trade_link_bad" || code === "trade_link_missing") {
    // Only a new or re-checked link helps: the form with «Изменить» and «где взять?», no retry.
    const reason = LINK_REASONS[refusal?.reason ?? ""];
    return (
      <div className="flex max-w-2xl flex-col gap-3">
        <p className="text-fg-muted">{reason ? t(`steam.${reason}`) : t(`errors.${code}`)}</p>
        <div className="bg-surface rounded-xl">
          <TradeLinkForm
            initial={{
              trade_link: user.trade_link,
              verdict: user.trade_link_verdict ?? null,
              reason: user.trade_link_reason ?? null,
            }}
            onChange={onLinkChange}
          />
        </div>
      </div>
    );
  }
  // Selling switched off: a retry cannot help. Steam, the rate and an outage may pass.
  const retry = code !== "sales_disabled";
  const text =
    code === "steam_refused"
      ? steam(refusal?.reason)
      : code === "sales_disabled"
        ? t("closed")
        : code === "rate_unavailable" || code === "sales_unavailable"
          ? t(`errors.${code}`)
          : t("loadFailed");
  return (
    <div className="bg-surface flex flex-col items-start gap-4 rounded-xl p-6">
      <p className="text-fg-muted">{text}</p>
      {retry ? (
        <Button variant="secondary" onClick={onRetry}>
          {t("retry")}
        </Button>
      ) : null}
    </div>
  );
}
