import { describe, expect, it } from "vitest";

import { actionWord, payloadLines, targetTypeLabel } from "./labels";

/**
 * Every action the API writes (`audit.record` call sites under apps/api/src/csmarket/modules,
 * found with `grep -rn 'action=' …` plus the `_audit(...)` helper of the payout routes and
 * `sales.card.<show|copy>`). A new call site must add its words here and in labels.ts.
 */
const API_ACTIONS = [
  "api_keys.limits",
  "api_keys.revoke",
  "api_keys.tariff",
  "orders.buy.retry",
  "orders.refund",
  "orders.trade.resolve",
  "p2p.card.add",
  "p2p.card.update",
  "p2p.incoming.credit",
  "p2p.settings.save",
  "payments.hold.release",
  "payments.hold.returned",
  "payments.review_limits.update",
  "payments.settings.save",
  "reviews.review.hide",
  "reviews.review.resolve",
  "reviews.review.unhide",
  "reviews.settings.save",
  "sales.attention.resolve",
  "sales.card.copy",
  "sales.card.show",
  "sales.payout.cancel",
  "sales.payout.claim",
  "sales.payout.paid",
  "sales.payout.reject",
  "sales.payout.release",
  "sales.payout.takeover",
  "sales.payout.undo",
  "sales.settings.save",
  "sales.user.block",
  "sales.user.unblock",
  "skins.alias.delete",
  "skins.alias.put",
  "skins.item.colors",
  "skins.item.hide",
  "skins.item.override",
  "skins.item.unhide",
  "skins.pricing.save",
  "users.ban",
  "users.risk.update",
  "users.unban",
  "wallet.adjust",
  "wallet.adjust_usd",
  "wallet.usd_switch",
];

const API_TARGET_TYPES = [
  "api_key",
  "kassa_review_limits",
  "order",
  "p2p_card",
  "p2p_incoming",
  "p2p_settings",
  "payment_hold",
  "payment_settings",
  "payout_request",
  "review",
  "review_settings",
  "sale",
  "sale_settings",
  "skin_alias",
  "skin_item",
  "skin_pricing_rules",
  "user",
];

describe("audit words", () => {
  it.each(API_ACTIONS)("names the action %s", (action) => {
    expect(actionWord(action).unknown).toBeNull();
  });

  it.each(API_TARGET_TYPES)("names the target type %s", (type) => {
    expect(targetTypeLabel(type)).not.toBe(type);
  });

  it("names a kassa review limit's field by its kassa", () => {
    expect(payloadLines({ "click.enabled": "false -> true", window_hours: 24 })).toEqual([
      { key: "click.enabled", label: "Click: включено", text: "нет → да" },
      { key: "window_hours", label: "окно, ч", text: "24" },
    ]);
  });
});
