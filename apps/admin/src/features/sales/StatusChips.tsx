/** A sale's and a payout request's status as a coloured chip (one tone per status). */
import { type SaleStatus } from "./api";
import { PAYOUT_LABELS, SALE_LABELS } from "./labels";
import { type PayoutStatus } from "./payoutsApi";

import { StatusChip, type Tone } from "@/components/StatusChip";

/** In flight amber, done green, a revert red, a closed one grey. */
export const SALE_TONES: Record<SaleStatus, Tone> = {
  creating: "muted",
  offered: "progress",
  hold: "progress",
  credited: "success",
  payout: "info",
  closed: "muted",
  reverted: "danger",
};

export const PAYOUT_TONES: Record<PayoutStatus, Tone> = {
  waiting_hold: "progress",
  to_pay: "info",
  paid: "success",
  rejected: "danger",
  canceled: "muted",
};

export function SaleStatusChip({
  status,
  danger = false,
}: {
  status: SaleStatus;
  danger?: boolean;
}) {
  return (
    <StatusChip tone={danger ? "danger" : SALE_TONES[status]}>{SALE_LABELS[status]}</StatusChip>
  );
}

/** A request canceled because the seller reverted the trade says so (`seller_reverted`). */
export function PayoutStatusChip({
  status,
  sellerReverted = false,
}: {
  status: PayoutStatus;
  sellerReverted?: boolean;
}) {
  if (status === "canceled" && sellerReverted) {
    return <StatusChip tone="danger">Отменено: продавец отменил обмен</StatusChip>;
  }
  return <StatusChip tone={PAYOUT_TONES[status]}>{PAYOUT_LABELS[status]}</StatusChip>;
}
