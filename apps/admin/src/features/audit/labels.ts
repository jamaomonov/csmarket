/**
 * Operator-facing Russian words for the audit log: actions, target types, payload keys. An
 * unknown action or key shows its code small beside «другое действие» / as itself — never alone
 * as the only word.
 */
import { providerLabel } from "@/features/users/labels";
import { formatSignedSum } from "@/lib/format";

/** Every action the API writes today (`audit.record` call sites). */
export const ACTION_LABELS: Readonly<Record<string, string>> = {
  "users.ban": "Блокировка",
  "users.unban": "Разблокировка",
  "wallet.adjust": "Изменение баланса",
  "skins.item.hide": "Скин скрыт",
  "skins.item.colors": "Цвета скина изменены",
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
  "sales.payout.claim": "Выплата взята в работу",
  "sales.payout.takeover": "Выплата забрана у другого",
  "sales.payout.release": "Выплата отпущена",
  "sales.payout.undo": "Выплата возвращена в очередь",
  "sales.payout.cancel": "Выплата отменена (откат)",
  "sales.card.show": "Номер карты показан",
  "sales.card.copy": "Номер карты скопирован",
  "sales.attention.resolve": "Продажа проверена",
  "sales.user.block": "Выкуп запрещён",
  "sales.user.unblock": "Выкуп разрешён",
  "sales.settings.save": "Настройки выкупа",
  "api_keys.tariff": "Тариф API-ключа",
  "api_keys.limits": "Лимиты API-ключа",
  "api_keys.revoke": "API-ключ отозван",
  "payments.settings.save": "Настройки оплаты",
  "payments.hold.release": "Платёж пропущен с проверки",
  "payments.hold.returned": "Платёж возвращён на карту",
  "p2p.card.add": "P2P: карта добавлена",
  "p2p.card.update": "P2P: карта изменена",
  "p2p.settings.save": "P2P: подключение и лимиты",
  "p2p.incoming.credit": "P2P: перевод зачислен вручную",
};

/** The action in words; an unknown one is «другое действие» with its code beside it. */
export function actionWord(action: string): { word: string; unknown: string | null } {
  const known = Object.hasOwn(ACTION_LABELS, action) ? ACTION_LABELS[action] : undefined;
  return known === undefined
    ? { word: "другое действие", unknown: action }
    : { word: known, unknown: null };
}

export const TARGET_TYPE_LABELS: Readonly<Record<string, string>> = {
  user: "Пользователь",
  skin_item: "Скин",
  skin_alias: "Синоним",
  order: "Заказ",
  api_key: "API-ключ",
  payout_request: "Выплата",
  sale: "Продажа",
  sale_settings: "Настройки выкупа",
  skin_pricing_rules: "Наценки",
  payment_settings: "Настройки оплаты",
  payment_hold: "Платёж на проверке",
  p2p_card: "P2P-карта",
  p2p_settings: "Настройки P2P",
  p2p_incoming: "P2P-перевод",
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
    case "sale":
      return `/sales/${safe}`;
    default:
      return null;
  }
}

/** Payload keys in words; a key not here shows as itself, small. */
const PAYLOAD_KEYS: Readonly<Record<string, string>> = {
  reason: "причина",
  amount_uzs: "сумма",
  alias: "синоним",
  text: "значение",
  from: "было",
  to: "стало",
  note: "комментарий",
  enabled: "включено",
  hidden: "скрыт",
  override: "выплачено несмотря на блокировку",
  was: "было",
  last4: "карта",
  items_repriced: "цены пересчитаны у скинов",
  margin_override_pp: "своя наценка, %",
  fixed_price_usd: "своя цена, $",
  colors: "цвета",
  number: "номер",
  provider: "касса",
  label: "название",
  topup: "пополнение",
  margin: "наценки",
  rate_cut_pct: "скидка с курса, %",
  balance_bonus_pct: "бонус за баланс, %",
  card_fee_pct: "комиссия карты, %",
  bank_fee_pct: "комиссия банка, %",
  card_min_uzs: "минимум на карту",
  min_sum_usd: "минимум продажи, $",
  max_sale_usd: "лимит продажи, $",
  max_user_day_usd: "лимит пользователя в день, $",
  max_day_usd: "лимит в день, $",
  unchanged: "без изменений",
};

/** Keys that only repeat what the target already says (the skin's slug beside its name). */
const HIDDEN_KEYS: ReadonlySet<string> = new Set(["slug", "user_id"]);

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

const MAX_VALUE = 120;

const WORDS: Readonly<Record<string, string>> = { true: "да", false: "нет", null: "—" };

/** `true` → «да», `"5 -> 7"` → «5 → 7», a long value cut; a UUID is never shown. */
function payloadValue(key: string, value: unknown): string {
  if (key === "amount_uzs" && (typeof value === "number" || typeof value === "string")) {
    return formatSignedSum(value);
  }
  if (key === "provider" && typeof value === "string") return providerLabel(value);
  const text = typeof value === "string" ? value : JSON.stringify(value);
  const shown = text
    .split(" -> ")
    .map((part) => WORDS[part] ?? part)
    .join(" → ");
  return shown.length > MAX_VALUE ? `${shown.slice(0, MAX_VALUE)}…` : shown;
}

export interface PayloadLine {
  key: string;
  /** The key in words; `null` when unknown (the page shows the key itself, small). */
  label: string | null;
  text: string;
}

/** The payload as short `key: value` lines, in the order stored; ids and slugs left out. */
export function payloadLines(
  payload: Record<string, unknown>,
  /** Keys the target already names (a hold's payment number). */
  shown: readonly string[] = [],
): PayloadLine[] {
  return Object.entries(payload)
    .filter(
      ([key, value]) =>
        !HIDDEN_KEYS.has(key) &&
        !shown.includes(key) &&
        !(typeof value === "string" && UUID.test(value)),
    )
    .map(([key, value]) => ({
      key,
      label: Object.hasOwn(PAYLOAD_KEYS, key) ? (PAYLOAD_KEYS[key] ?? null) : null,
      text: payloadValue(key, value),
    }));
}
