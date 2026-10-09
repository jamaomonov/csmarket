/** Shared fixtures for the orders and trades tests. Fake numbers and ids only. */
import {
  type AdminOrderDetail,
  type AdminLisskinsPurchaseOut,
  type AdminOrderRow,
  type AdminSkinslinkPurchaseOut,
  type AdminTradeOut,
} from "./api";

export const ORDER_ROW: AdminOrderRow = {
  number: "O7K2M9QX",
  status: "buying",
  name: "AK-47 | Redline (Field-Tested)",
  phase: null,
  price_uzs: "171800",
  paid_with: "click",
  user: { id: "u-1", display_name: "Ivan" },
  created_at: "2026-09-30T10:00:00Z",
  attention_reason: null,
  protected_until: null,
  protected_estimated: false,
};

export const TRADE: AdminTradeOut = {
  project_id: "6f1c2a52-0000-4000-8000-000000000001",
  waxpeer_id: 60000009,
  paid_units: 13500,
  bought_units: 13200,
  status: 4,
  escrow_status: "pending",
  trade_id: "7000000001",
  offer_url: "https://steamcommunity.com/tradeoffer/7000000001/",
  send_until: "2026-09-30T10:30:00Z",
  release_date: "2026-10-07T10:00:00Z",
  accepted_at: "2026-09-30T10:20:00Z",
  is_released: false,
  reason: "seller_cancelled",
  penalties: { stuck: 1 },
  seller: { name: "SellerName", level: 12 },
  buy_pending: false,
  attention_reason: null,
  resolved_at: null,
  resolved_note: null,
};

export const DETAIL: AdminOrderDetail = {
  order: {
    number: "O7K2M9QX",
    status: "buying",
    market_hash_name: "AK-47 | Redline (Field-Tested)",
    phase: null,
    slug: "ak-47-redline-field-tested",
    source: "waxpeer",
    offer_id: "wx:4242",
    listing_id: 4242,
    cost_units: 13500,
    cost_usd: "13.500000",
    price_usd: "13.580000",
    price_uzs: "171800",
    fx_rate: "12650.5000",
    fx_uplift_pct: "0.00",
    margin_usd: "0.380000",
    protected_until: null,
    protected_estimated: false,
    // Fake, already-masked link: the token never reaches the page.
    trade_link_masked: "https://steamcommunity.com/tradeoffer/new/?partner=1&token=••••XY",
    paid_with: "click",
    created_at: "2026-09-30T10:00:00Z",
    updated_at: "2026-09-30T10:05:00Z",
    expires_at: "2026-09-30T10:30:00Z",
    paid_at: "2026-09-30T10:01:00Z",
    claimed_at: "2026-09-30T10:01:05Z",
    trade_sent_at: null,
    delivered_at: null,
    cancelled_at: null,
    failed_at: null,
    refunded_at: null,
    refunded_to: null,
    failure_reason: null,
  },
  user: { id: "u-1", display_name: "Ivan" },
  trade: TRADE,
  skinslink: null,
  lisskins: null,
  payments: [
    {
      id: "p-1",
      provider: "click",
      status: "succeeded",
      amount_uzs: "171800",
      created_at: "2026-09-30T10:00:30Z",
    },
  ],
  can_refund: false,
  can_retry: false,
};

/** An order whose lost buy answer waits for an admin, resolved, so both money actions are open. */
export const RESOLVED: AdminOrderDetail = {
  ...DETAIL,
  trade: {
    ...TRADE,
    waxpeer_id: null,
    bought_units: null,
    status: null,
    trade_id: null,
    offer_url: null,
    attention_reason: "buy_unconfirmed",
    resolved_at: "2026-09-30T11:00:00Z",
    resolved_note: "проверил в кабинете",
  },
  can_refund: true,
  can_retry: true,
};

export const ATTENTION: AdminOrderDetail = {
  ...DETAIL,
  trade: { ...TRADE, attention_reason: "ambiguous_trade" },
};

export const SKINSLINK: AdminSkinslinkPurchaseOut = {
  merchant_tx_id: "6f1c2a52-0000-4000-8000-000000000001",
  asset_id: "380",
  purchase_id: 178,
  status: "active",
  offer_id: "6912345678",
  offer_url: "https://steamcommunity.com/tradeoffer/6912345678/",
  fail_reason: null,
  amount_usd: "12.000000",
  hold_end_date: null,
  buy_pending: false,
  buy_unconfirmed_at: null,
  attention_reason: "rolled_back",
  resolved_at: null,
};

export const LISSKINS: AdminLisskinsPurchaseOut = {
  custom_id: "6f1c2a52-0000-4000-8000-000000000001",
  skin_id: 125345,
  purchase_id: 55,
  status: "wait_accept",
  return_reason: null,
  error: null,
  offer_id: "7252638866",
  offer_url: "https://steamcommunity.com/tradeoffer/7252638866/",
  offer_expiry_at: "2026-10-07T19:50:35Z",
  amount_usd: "12.340000",
  buy_pending: false,
  buy_unconfirmed_at: null,
  attention_reason: "rolled_back",
  resolved_at: null,
};
