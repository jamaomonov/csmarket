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
};

export function actionLabel(action: string): string {
  return ACTION_LABELS[action] ?? action;
}

export const TARGET_TYPE_LABELS: Readonly<Record<string, string>> = {
  user: "Пользователь",
  skin_item: "Скин",
  skin_alias: "Синоним",
};

export function targetTypeLabel(type: string): string {
  return TARGET_TYPE_LABELS[type] ?? type;
}

/** Where a target has an admin page of its own; `null` for plain text. */
export function targetPath(type: string, id: string): string | null {
  return type === "user" ? `/users/${encodeURIComponent(id)}` : null;
}

const PAYLOAD_KEYS: Readonly<Record<string, string>> = {
  reason: "причина",
  amount_uzs: "сумма",
  slug: "slug",
  alias: "синоним",
  text: "значение",
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
