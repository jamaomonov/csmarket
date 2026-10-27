/** The analytics world of the API tests (analytics_world.py), as the API answers it. */
import { type BusinessOut, type CalendarOut, type Totals } from "./api";

const ZERO_TOTALS: Totals = {
  orders: 0,
  revenue: { uzs: "0", usd: "0.000000" },
  cost: { uzs: "0", usd: "0.000000" },
  profit: { uzs: "0", usd: "0.000000" },
  margin_percent: "0",
  earned_profit_uzs: "0",
  in_flight_profit_uzs: "0",
  in_flight_orders: 0,
  average_check_uzs: "0",
  buyback_profit_uzs: "0",
  buyback_profit_usd: "0.000000",
  refunds: 0,
  refunds_uzs: "0",
  new_buyers: 0,
  gross_profit_uzs: "0",
  partners_uzs: "0",
};

export const BUSINESS: BusinessOut = {
  since: "2026-10-09",
  until: "2026-10-10",
  channel: "all",
  totals: {
    orders: 4,
    revenue: { uzs: "430000", usd: "33.000000" },
    cost: { uzs: "378251", usd: "29.900000" },
    profit: { uzs: "51749", usd: "3.100000" },
    margin_percent: "12.0",
    earned_profit_uzs: "35604",
    in_flight_profit_uzs: "16145",
    in_flight_orders: 1,
    average_check_uzs: "107500",
    buyback_profit_uzs: "6505",
    buyback_profit_usd: "0.514000",
    refunds: 1,
    refunds_uzs: "90000",
    new_buyers: 3,
    partners_uzs: "12000",
    gross_profit_uzs: "58254",
  },
  previous: {
    ...ZERO_TOTALS,
    orders: 2,
    revenue: { uzs: "200000", usd: "16.000000" },
    gross_profit_uzs: "60000",
  },
  by_day: [
    {
      day: "2026-10-09",
      orders: 3,
      revenue_uzs: "300000",
      earned_profit_uzs: "35604",
      in_flight_profit_uzs: "0",
      buyback_profit_uzs: "6505",
    },
    {
      day: "2026-10-10",
      orders: 1,
      revenue_uzs: "130000",
      earned_profit_uzs: "0",
      in_flight_profit_uzs: "16145",
      buyback_profit_uzs: "0",
    },
  ],
  sources: [
    {
      key: "waxpeer",
      orders: 2,
      revenue_uzs: "200000",
      profit_uzs: "41868",
      profit_usd: "2.500000",
      margin_percent: "20.9",
    },
    {
      key: "skinslink",
      orders: 1,
      revenue_uzs: "130000",
      profit_uzs: "16145",
      profit_usd: "1.000000",
      margin_percent: "12.4",
    },
    {
      key: "lisskins",
      orders: 1,
      revenue_uzs: "100000",
      profit_uzs: "-6264",
      profit_usd: "-0.400000",
      margin_percent: "-6.3",
    },
  ],
  channels: [
    {
      key: "Сайт",
      orders: 3,
      revenue_uzs: "380000",
      profit_uzs: "46026",
      profit_usd: "2.600000",
      margin_percent: "12.1",
    },
    {
      key: "Partner",
      orders: 1,
      revenue_uzs: "50000",
      profit_uzs: "5723",
      profit_usd: "0.500000",
      margin_percent: "11.4",
    },
  ],
  payments: [
    {
      key: "payme",
      orders: 3,
      revenue_uzs: "380000",
      profit_uzs: "46026",
      profit_usd: "2.600000",
      margin_percent: "12.1",
    },
    {
      key: "usd_wallet",
      orders: 1,
      revenue_uzs: "50000",
      profit_uzs: "5723",
      profit_usd: "0.500000",
      margin_percent: "11.4",
    },
  ],
  kassa_fees: [{ provider: "payme", payments: 1, fee_uzs: "1500" }],
  categories: [
    {
      key: "rifles",
      orders: 4,
      revenue_uzs: "430000",
      profit_uzs: "51749",
      profit_usd: "3.100000",
      margin_percent: "12.0",
    },
  ],
  top_skins: [
    {
      name: "AK-47 | Redline (Field-Tested)",
      image_url: null,
      orders: 1,
      revenue_uzs: "150000",
      profit_uzs: "36145",
    },
  ],
  buyers: {
    new: { count: 3, revenue_uzs: "330000" },
    returning: { count: 1, revenue_uzs: "100000" },
    top: [
      {
        id: "u-1",
        display_name: "Ivan",
        avatar_url: null,
        orders: 1,
        revenue_uzs: "150000",
        profit_uzs: "36145",
      },
    ],
  },
  refunds: {
    count: 1,
    amount_uzs: "90000",
    by_source: [{ key: "waxpeer", count: 1, amount_uzs: "90000" }],
    by_reason: [{ key: "other", count: 1, amount_uzs: "90000" }],
  },
  buyback: {
    count: 1,
    income_usd: "10.000000",
    to_cards_uzs: "0",
    to_balances_uzs: "120000",
    to_pay_uzs: "0",
    profit_uzs: "6505",
    profit_usd: "0.514000",
  },
};

export const OCTOBER: CalendarOut = {
  month: "2026-10",
  channel: "all",
  days: Array.from({ length: 31 }, (_, i) => {
    const day = `2026-10-${String(i + 1).padStart(2, "0")}`;
    const profit = i === 8 ? "35604" : i === 9 ? "-6264" : "0";
    return {
      day,
      orders: profit === "0" ? 0 : 2,
      revenue_uzs: profit === "0" ? "0" : "250000",
      earned_profit_uzs: profit,
      in_flight_profit_uzs: "0",
      buyback_profit_uzs: "0",
    };
  }),
};
