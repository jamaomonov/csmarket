/** Query keys of the orders area, shared by the page that reads and the actions that write. */

/** One order's page (`GET /admin/orders/{number}`). */
export const detailKey = (number: string) => ["admin", "orders", "detail", number] as const;

/** Every trades page (the attention queue included). */
export const TRADES_KEY = ["admin", "trades"] as const;
