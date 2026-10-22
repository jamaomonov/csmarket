/**
 * The one dictionary of statuses and reasons the admin shows (admin UX audit §6). Every chip and
 * every reason line reads its words here; a code the dictionary does not know reads «другой
 * статус» / «другая причина» with the code itself, small, beside it — never a bare code alone.
 *
 * Chips are lower-case («оплачен», «к выплате»); a tab or a heading capitalises with `capital`.
 *
 * Type-only imports: the dictionary must not pull the feature API modules in at run time.
 */
import type { Tone } from "@/components/StatusChip";
import type { AttentionReason, FailureReason, OrderStatus } from "@/features/orders/kinds";
import type { IncomingResult, RequestStatus } from "@/features/p2p/api";
import type { PaymentStatus } from "@/features/payments/kinds";
import type { AttentionReason as SaleAttention, SaleStatus } from "@/features/sales/api";
import type { PayoutFlag, PayoutStatus } from "@/features/sales/payoutsApi";
import type { ReconFlag } from "@/features/sales/reconApi";
import type { TradeRowState } from "@/features/trades/kinds";
import type { TopupStatus } from "@/features/users/api";

export interface StatusWord {
  label: string;
  tone: Tone;
}

const ORDER: Record<OrderStatus | "accepted", StatusWord> = {
  pending: { label: "ждёт оплаты", tone: "muted" },
  held: { label: "на проверке", tone: "progress" },
  paid: { label: "оплачен", tone: "progress" },
  buying: { label: "покупаем", tone: "progress" },
  trade_sent: { label: "обмен отправлен", tone: "progress" },
  // Accepted while Steam's protection runs (shown with «защита до …»): the same word as a trade.
  accepted: { label: "принят", tone: "info" },
  delivered: { label: "получен", tone: "success" },
  cancelled: { label: "отменён", tone: "muted" },
  failed: { label: "не получилось", tone: "danger" },
  returned: { label: "обмен не состоялся", tone: "neutral" },
};

/** «Обмены» rows: the same words as an order where the states meet. */
const TRADE: Record<TradeRowState, StatusWord> = {
  pending: ORDER.pending,
  buying: ORDER.buying,
  sent: ORDER.trade_sent,
  hold: ORDER.accepted,
  delivered: ORDER.delivered,
  refunded: { label: "возврат", tone: "neutral" },
  cancelled: ORDER.cancelled,
  failed_held: ORDER.failed,
};

const PAYMENT: Record<PaymentStatus, StatusWord> = {
  created: { label: "создан", tone: "muted" },
  pending: { label: "ждёт кассу", tone: "progress" },
  succeeded: { label: "оплачен", tone: "success" },
  failed: { label: "не прошёл", tone: "danger" },
  cancelled: { label: "отменён", tone: "muted" },
  refunded: { label: "возвращён", tone: "neutral" },
};

const TOPUP: Record<TopupStatus, StatusWord> = {
  pending: { label: "ждёт оплаты", tone: "progress" },
  succeeded: { label: "зачислено", tone: "success" },
  expired: { label: "истекло", tone: "muted" },
  reversed: { label: "отменено кассой", tone: "danger" },
  held: { label: "на проверке", tone: "progress" },
  rejected: { label: "возвращено на карту", tone: "muted" },
};

const SALE: Record<SaleStatus, StatusWord> = {
  creating: { label: "создаётся", tone: "muted" },
  offered: { label: "обмен отправлен", tone: "progress" },
  hold: { label: "холд 7 дней", tone: "progress" },
  credited: { label: "зачислено на баланс", tone: "success" },
  payout: { label: "выплата на карту", tone: "info" },
  closed: { label: "закрыта", tone: "muted" },
  reverted: { label: "откат обмена", tone: "danger" },
};

const PAYOUT: Record<PayoutStatus | "seller_reverted", StatusWord> = {
  waiting_hold: { label: "ждёт 7 дней", tone: "progress" },
  to_pay: { label: "к выплате", tone: "info" },
  paid: { label: "выплачено", tone: "success" },
  rejected: { label: "отклонено", tone: "danger" },
  canceled: { label: "отменено", tone: "muted" },
  // A request canceled because the seller reverted the trade says so.
  seller_reverted: { label: "отменено: продавец отменил обмен", tone: "danger" },
};

const P2P_INCOMING: Record<IncomingResult, StatusWord> = {
  matched: { label: "зачислен", tone: "success" },
  unmatched: { label: "не сопоставлен", tone: "progress" },
  ignored: { label: "не наш / не перевод", tone: "muted" },
};

const P2P_REQUEST: Record<RequestStatus, StatusWord> = {
  pending: { label: "ждёт перевода", tone: "progress" },
  paid: { label: "оплачена", tone: "success" },
  expired: { label: "истекла", tone: "muted" },
  cancelled: { label: "отменена", tone: "muted" },
};

/** A supplier's own status word (Skinslink, LIS-SKINS) as we have seen them. */
const SUPPLIER: Record<string, StatusWord> = {
  created: { label: "создана", tone: "muted" },
  pending: { label: "ждёт", tone: "progress" },
  active: { label: "идёт", tone: "progress" },
  wait_accept: { label: "ждёт принятия", tone: "progress" },
  hold: { label: "на холде", tone: "info" },
  accepted: { label: "принят", tone: "info" },
  completed: { label: "завершена", tone: "success" },
  success: { label: "завершена", tone: "success" },
  return: { label: "возврат", tone: "neutral" },
  refunded: { label: "деньги вернулись", tone: "neutral" },
  failed: { label: "не удалась", tone: "danger" },
  canceled: { label: "отменена", tone: "muted" },
  cancelled: { label: "отменена", tone: "muted" },
};

/** Waxpeer's trade status codes we know (`orders.trades`). */
const WAXPEER: Record<string, StatusWord> = {
  "4": { label: "предложение отправлено", tone: "progress" },
  "5": { label: "выдан покупателю", tone: "success" },
  "6": { label: "не состоялся", tone: "neutral" },
};

export const STATUSES = {
  order: ORDER,
  trade: TRADE,
  payment: PAYMENT,
  topup: TOPUP,
  sale: SALE,
  payout: PAYOUT,
  p2pIncoming: P2P_INCOMING,
  p2pRequest: P2P_REQUEST,
  supplier: SUPPLIER,
  waxpeer: WAXPEER,
} as const;

export type StatusKind = keyof typeof STATUSES;

export const OTHER_STATUS = "другой статус";
export const OTHER_REASON = "другая причина";

export interface Looked<T> {
  word: T;
  /** The raw code when the dictionary does not know it (shown small beside the word). */
  unknown: string | null;
}

function lookup<T>(table: Readonly<Record<string, T>>, code: string): T | undefined {
  return Object.hasOwn(table, code) ? table[code] : undefined;
}

export function statusWord(kind: StatusKind, code: string): Looked<StatusWord> {
  const known = lookup<StatusWord>(STATUSES[kind], code);
  return known === undefined
    ? { word: { label: OTHER_STATUS, tone: "muted" }, unknown: code }
    : { word: known, unknown: null };
}

const FAILURE: Record<FailureReason, string> = {
  sold_out: "скин продан",
  source_low_balance: "не хватило денег на площадке",
  invalid_trade_link: "неверная трейд-ссылка",
  not_accepted: "обмен не принят",
  trade_hold: "задержка обменов Steam",
  price_moved: "цена поставщика выросла",
  source_refused: "продавец не отдал скин",
  admin: "вернул администратор",
};

const ORDER_ATTENTION: Record<AttentionReason, string> = {
  buy_unconfirmed: "ответ площадки потерян",
  ambiguous_trade: "несколько обменов",
  rolled_back: "откат после получения",
  source_forbidden: "площадка: IP не в белом списке",
  audit_divergence: "расхождение со сверкой",
};

const SALE_ATTENTION: Record<SaleAttention, string> = {
  rolled_back: "откат после выплаты — разобрать вручную",
  late_deposit: "закрыта, но Skinslink видит обмен — разобрать вручную",
  credit_blocked: "кошелёк заморожен — зачисление ждёт разморозки",
};

const PAYOUT_FLAG: Record<PayoutFlag, string> = {
  banned: "аккаунт заблокирован",
  wallet_frozen: "кошелёк заморожен",
  sell_blocked: "выкуп запрещён",
  shared_card: "карта у других",
  new_account: "новый аккаунт",
  rolled_back: "обмен отменён",
  seller_reverted: "продавец отменил обмен",
};

const RECON_FLAG: Record<ReconFlag, string> = {
  short: "недозачислено",
  missing: "нет зачисления",
  reverted: "откат",
};

const HOLD_REASON: Record<string, string> = {
  kassa_limit: "лимит кассы",
  user_limit: "лимит пользователя",
  check_failed: "проверка не сработала",
};

const HOLD_DECISION: Record<string, string> = {
  released: "пропущен",
  returned: "возвращён на карту",
  reversed_by_kassa: "отменён кассой",
};

/** Analytics' «Возвраты»: an order's failure reason, `other` when none was set. */
const RETURN: Record<string, string> = { ...FAILURE, other: "без причины" };

/** Why a supplier failed or returned a purchase, as far as we have seen the words. */
const SUPPLIER_REASON: Record<string, string> = {
  trade_create_error: "Steam не создал обмен",
  not_accepted: "обмен не принят",
  canceled: "обмен отменён",
  cancelled: "обмен отменён",
  declined: "покупатель отклонил обмен",
  expired: "время на обмен вышло",
};

const CATALOGUE_JOB: Record<string, string> = {
  thin_snapshot: "Waxpeer прислал неполный список — цены остались прежними",
};

export const REASONS = {
  failure: FAILURE,
  orderAttention: ORDER_ATTENTION,
  saleAttention: SALE_ATTENTION,
  payoutFlag: PAYOUT_FLAG,
  reconFlag: RECON_FLAG,
  holdReason: HOLD_REASON,
  holdDecision: HOLD_DECISION,
  return: RETURN,
  supplier: SUPPLIER_REASON,
  catalogueJob: CATALOGUE_JOB,
} as const;

export type ReasonKind = keyof typeof REASONS;

export function reasonWord(kind: ReasonKind, code: string): Looked<string> {
  const known = lookup<string>(REASONS[kind], code);
  return known === undefined
    ? { word: OTHER_REASON, unknown: code }
    : { word: known, unknown: null };
}

/** The reason as plain text (a tooltip, an `aria-label`): «другая причина (code)» when unknown. */
export function reasonText(kind: ReasonKind, code: string): string {
  const r = reasonWord(kind, code);
  return r.unknown === null ? r.word : `${r.word} (${r.unknown})`;
}

/** The status as plain text: «другой статус (code)» when unknown. */
export function statusText(kind: StatusKind, code: string): string {
  const s = statusWord(kind, code);
  return s.unknown === null ? s.word.label : `${s.word.label} (${s.unknown})`;
}

/** «к выплате» → «К выплате»: a tab or a heading made of a chip's word. */
export function capital(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}
