import type { SaleItemOut, SaleOut } from "@/lib/sales";

export function saleItem(assetId: string, over: Partial<SaleItemOut> = {}): SaleItemOut {
  return {
    asset_id: assetId,
    name: "USP-S | Tropical Breeze (Minimal Wear)",
    image_url: null,
    exterior: "MW",
    rarity_color: "#4b69ff",
    price_uzs: "6100",
    ...over,
  };
}

/** A sale as `GET /sales/{number}` answers it; tests override what they need. */
export function saleOut(number: string, over: Partial<SaleOut> = {}): SaleOut {
  return {
    number,
    status: "hold",
    payout_to: "balance",
    card: null,
    items_uzs: "10800",
    bonus_uzs: "100",
    fee_uzs: "0",
    payout_uzs: "10900",
    items: [saleItem("1")],
    offer: null,
    money_at: "2026-10-15T16:14:00Z",
    payout_status: null,
    payout_reject_reason: null,
    created_at: "2026-10-08T16:12:00Z",
    ...over,
  };
}
