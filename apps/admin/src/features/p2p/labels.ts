/** Words of the «P2P» pages (Russian) and one tone per state. */
import { type IncomingResult, type RequestStatus } from "./api";

import { type Tone } from "@/components/StatusChip";

export const RESULT_LABELS: Record<IncomingResult, string> = {
  matched: "зачислен",
  unmatched: "не сопоставлен",
  ignored: "не наш / не перевод",
};

export const RESULT_TONES: Record<IncomingResult, Tone> = {
  matched: "success",
  unmatched: "progress",
  ignored: "muted",
};

export const REQUEST_LABELS: Record<RequestStatus, string> = {
  pending: "ждёт перевода",
  paid: "оплачена",
  expired: "истекла",
  cancelled: "отменена",
};

export const REQUEST_TONES: Record<RequestStatus, Tone> = {
  pending: "progress",
  paid: "success",
  expired: "muted",
  cancelled: "muted",
};

/** `"70000.00"` → 70000 (whole soʻm; the journal keeps tiyin as the bank sent them). */
export function wholeSom(value: string | null): number {
  return value === null ? 0 : Math.trunc(Number(value));
}
