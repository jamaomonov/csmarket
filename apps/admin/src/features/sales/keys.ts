/** Query keys of the «Выкуп» area, shared by the pages that read and the actions that write. */

export const PAYOUTS_KEY = ["admin", "sales", "payouts"] as const;
export const payoutKey = (id: string) => ["admin", "sales", "payout", id] as const;
export const SALES_LIST_KEY = ["admin", "sales", "list"] as const;
export const saleKey = (number: string) => ["admin", "sales", "one", number] as const;
export const SALE_SETTINGS_KEY = ["admin", "sales", "settings"] as const;
