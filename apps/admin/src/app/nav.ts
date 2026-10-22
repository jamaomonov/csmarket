/**
 * The admin's menu (admin UX audit §1): Дашборд, then the groups Очередь, Деньги, Люди,
 * Аналитика, Настройки, Журнал. The top bar, the phone's bottom bar and its «Ещё» sheet all read
 * from here, so a page is listed once.
 */

/** What waits for an operator, counted by the dashboard. */
export type Counter = "attention" | "toPay" | "salesAttention" | "holds";

export interface NavItem {
  to: string;
  label: string;
  /** The bottom bar's short name. */
  short?: string;
  end?: boolean;
  /** Other path prefixes the item stands for (an order page belongs to «Обмены»). */
  also?: readonly string[];
  counter?: Counter;
}

export interface NavGroup {
  label: string;
  items: readonly NavItem[];
}

export const DASHBOARD: NavItem = { to: "/", label: "Дашборд", end: true };

const TRADES: NavItem = {
  to: "/trades",
  label: "Обмены",
  also: ["/orders/"],
  counter: "attention",
};
const PAYOUTS: NavItem = {
  to: "/payouts",
  label: "Заявки на выплату",
  short: "Выплаты",
  counter: "toPay",
};
const HOLDS: NavItem = {
  to: "/payment-holds",
  label: "На проверке",
  short: "Проверка",
  counter: "holds",
};

export const GROUPS: readonly NavGroup[] = [
  { label: "Очередь", items: [TRADES, PAYOUTS, HOLDS] },
  {
    label: "Деньги",
    items: [
      { to: "/payments", label: "Платежи" },
      { to: "/p2p", label: "P2P" },
      { to: "/sales", label: "Продажи", counter: "salesAttention" },
      { to: "/sales/reconciliation", label: "Сверка" },
    ],
  },
  {
    label: "Люди",
    items: [
      { to: "/users", label: "Пользователи", also: ["/api-keys"] },
      { to: "/sale-blocks", label: "Запрет выкупа" },
    ],
  },
  { label: "Аналитика", items: [{ to: "/analytics", label: "Аналитика" }] },
  {
    label: "Настройки",
    items: [
      { to: "/pricing", label: "Цены" },
      { to: "/catalogue", label: "Каталог" },
      { to: "/sale-settings", label: "Настройки выкупа" },
      { to: "/payment-settings", label: "Оплата" },
    ],
  },
  { label: "Журнал", items: [{ to: "/audit", label: "Журнал" }] },
];

/** The phone's bottom bar: the three queues; everything else is behind «Ещё». */
export const BOTTOM_ITEMS: readonly NavItem[] = [TRADES, PAYOUTS, HOLDS];

export const COUNTER_LABEL: Record<Counter, string> = {
  attention: "ждут внимания",
  toPay: "к выплате",
  salesAttention: "продажи ждут проверки",
  holds: "Платежи на проверке",
};

const ALL: readonly NavItem[] = [DASHBOARD, ...GROUPS.flatMap((g) => g.items)];

/** How long a prefix of `pathname` the item matches; -1 when it does not. */
function matchLength(item: NavItem, pathname: string): number {
  const also = (item.also ?? []).filter((p) => pathname.startsWith(p));
  if (also.length > 0) return Math.max(...also.map((p) => p.length));
  if (item.end === true) return pathname === item.to ? item.to.length : -1;
  return pathname === item.to || pathname.startsWith(`${item.to}/`) ? item.to.length : -1;
}

/** The menu item a page belongs to: the longest match wins («Сверка» over «Продажи»). */
export function currentItem(pathname: string): NavItem | undefined {
  let best: NavItem | undefined;
  let bestLength = -1;
  for (const item of ALL) {
    const length = matchLength(item, pathname);
    if (length > bestLength) {
      best = item;
      bestLength = length;
    }
  }
  return best;
}

/** The sum of the counters of `items` (a closed menu, «Ещё»). */
export function countOf(items: readonly NavItem[], counters: Record<Counter, number>): number {
  return items.reduce((sum, i) => sum + (i.counter === undefined ? 0 : counters[i.counter]), 0);
}
