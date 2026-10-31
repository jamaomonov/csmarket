/** Test data for «Мои сделки». */
import { type Deal, type DealRow, type DeskItem, type StockItem } from "./api";

export function item(over: Partial<DeskItem> = {}): DeskItem {
  return {
    id: "i1",
    name: "AK-47 | Redline (Field-Tested)",
    asset_id: "100",
    image_url: null,
    skinslink_usd: "800",
    destination: "skinslink",
    cost_usd: "733.333333",
    state: "open",
    deposit_id: null,
    sold_where: null,
    sold_amount: null,
    sold_currency: null,
    sold_usd: null,
    resolved_at: null,
    note: null,
    ...over,
  };
}

export function deal(over: Partial<Deal> = {}): Deal {
  return {
    id: "d1",
    status: "paid",
    trader: "trader one",
    note: null,
    trade_link: "https://steamcommunity.com/tradeoffer/new/?partner=1&token=abc",
    paid_amount: "1100",
    paid_currency: "USD",
    rate: null,
    paid_usd: "1100",
    method: "direct",
    guarantor: null,
    paid_at: "2026-10-29T10:00:00Z",
    guarantor_released_at: null,
    created_at: "2026-10-29T10:00:00Z",
    updated_at: "2026-10-29T10:00:00Z",
    items: [
      item(),
      item({
        id: "i2",
        name: "AWP | Asiimov (Field-Tested)",
        asset_id: "101",
        skinslink_usd: "400",
        cost_usd: "366.666667",
      }),
    ],
    deposits: [],
    protected_until: null,
    profit_usd: "0",
    expected_profit_usd: "100",
    resolved: false,
    ...over,
  };
}

export function row(over: Partial<DealRow> = {}): DealRow {
  return {
    id: "d1",
    status: "paid",
    trader: "trader one",
    method: "direct",
    guarantor: null,
    note: null,
    created_at: "2026-10-29T10:00:00Z",
    paid_amount: "14300000",
    paid_currency: "UZS",
    paid_usd: "1100",
    items: 2,
    first_item: { name: "AK-47 | Redline (Field-Tested)", image_url: null },
    skinslink_usd: "1200",
    profit_usd: "0",
    expected_profit_usd: "100",
    resolved: false,
    protected_until: null,
    guarantor_released_at: null,
    ...over,
  };
}

export function stockItem(over: Partial<StockItem> = {}): StockItem {
  return {
    ...item({ id: "s1", destination: "stock", cost_usd: "54" }),
    deal_id: "d1",
    trader: "trader one",
    bought_at: "2026-10-20T10:00:00Z",
    ...over,
  };
}
