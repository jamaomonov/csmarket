/** Operator-facing Russian labels for the audit log. Unknown values fall back to the raw string. */
import { formatSignedSum } from "@/lib/format";

/** Every action the API writes today (`audit.record` call sites). */
export const ACTION_LABELS: Readonly<Record<string, string>> = {
  "users.ban": "Блокировка",
  "users.unban": "Разблокировка",
  "wallet.adjust": "Изменение баланса",
  "skins.item.hide": "Скин скрыт",
  "skins.item.unhide": "Скин показан",
  "skins.alias.put": "Синоним сохранён",
  "skins.alias.delete": "Синоним удалён",
  "skins.item.override": "Цена скина вручную",
  "skins.pricing.save": "Наценки сохранены",
  "wallet.adjust_usd": "Изменение USD-баланса",
  "wallet.usd_switch": "USD-кошелёк вкл/выкл",
  "orders.trade.resolve": "Заказ разобран",
  "orders.refund": "Возврат по заказу",
  "orders.buy.retry": "Повтор покупки",
  "sales.payout.paid": "Выплата отмечена",
  "sales.payout.reject": "Выплата отклонена",
  "sales.settings.save": "Настройки выкупа",
  "api_keys.tariff": "Тариф API-ключа",
  "api_keys.limits": "Лимиты API-ключа",
  "api_keys.revoke": "API-ключ отозван",
};

export function actionLabel(action: string): string {
  return ACTION_LABELS[action] ?? action;
}

export const TARGET_TYPE_LABELS: Readonly<Record<string, string>> = {
  user: "Пользователь",
  skin_item: "Скин",
  skin_alias: "Синоним",
  order: "Заказ",
  api_key: "API-ключ",
  payout_request: "Выплата",
  sale_settings: "Настройки выкупа",
  skin_pricing_rules: "Наценки",
};

export function targetTypeLabel(type: string): string {
  return TARGET_TYPE_LABELS[type] ?? type;
}

/** Where a target has an admin page of its own; `null` for plain text. */
export function targetPath(type: string, id: string): string | null {
  const safe = encodeURIComponent(id);
  switch (type) {
    case "user":
      return `/users/${safe}`;
    case "order":
      return `/orders/${safe}`;
    case "api_key":
      return `/api-keys/${safe}`;
    case "payout_request":
      return `/payouts/${safe}`;
    default:
      return null;
  }
}

const PAYLOAD_KEYS: Readonly<Record<string, string>> = {
  reason: "причина",
  amount_uzs: "сумма",
  slug: "slug",
  alias: "синоним",
  text: "значение",
  from: "было",
  to: "стало",
  note: "комментарий",
  enabled: "включён",
  hidden: "скрыт",
};

const MAX_VALUE = 120;

function payloadValue(key: string, value: unknown): string {
  if (key === "amount_uzs" && (typeof value === "number" || typeof value === "string")) {
    return formatSignedSum(value);
  }
  const text = typeof value === "string" ? value : JSON.stringify(value);
  return text.length > MAX_VALUE ? `${text.slice(0, MAX_VALUE)}…` : text;
}

/** The payload as short `key: value` pairs, in the order stored. */
export function payloadLines(payload: Record<string, unknown>): { key: string; text: string }[] {
  return Object.entries(payload).map(([key, value]) => ({
    key,
    text: `${PAYLOAD_KEYS[key] ?? key}: ${payloadValue(key, value)}`,
  }));
}
