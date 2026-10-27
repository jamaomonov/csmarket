/** Partners as the API answers them, for the admin tests. */
import { type AdminPartner, type PartnerDetail } from "./api";

export const PARTNER: AdminPartner = {
  user_id: "u-partner",
  display_name: "ZufarMax",
  steam_id: "76561198000000555",
  code: "zufarmax",
  percent: "1.0",
  term_months: 6,
  active: true,
  note: "канал в TG",
  created_at: "2026-10-27T10:00:00Z",
  totals: {
    visits: 120,
    accounts: 9,
    purchases: 7,
    revenue_uzs: "1200000",
    held_uzs: "3436",
    credited_uzs: "8564",
  },
};

export const DETAIL: PartnerDetail = {
  partner: PARTNER,
  months: [
    {
      month: "2026-10-01",
      visits: 120,
      accounts: 9,
      purchases: 7,
      revenue_uzs: "1200000",
      earned_uzs: "12000",
    },
  ],
  rewards: [
    {
      order_number: "DTN44T1E",
      delivered_at: "2026-10-26T10:00:00Z",
      base_uzs: "171800",
      percent: "1.0",
      amount_uzs: "1718",
      status: "held",
      available_at: "2026-11-03T10:00:00Z",
      credited_at: null,
      cancelled_reason: null,
    },
  ],
  next_cursor: null,
};
