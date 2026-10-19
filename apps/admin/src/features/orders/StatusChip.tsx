import { type AttentionReason, type OrderStatus } from "./kinds";
import { ATTENTION_LABELS, STATUS_LABELS, STATUS_TONE } from "./labels";

import { StatusChip } from "@/components/StatusChip";
import { formatDateTime } from "@/lib/format";

interface OrderStatusChipProps {
  status: OrderStatus;
  /** When Steam's protection of an accepted trade ends, if it runs. */
  protectedUntil?: string | null;
  /** The end is our estimate (LIS-SKINS). */
  estimated?: boolean;
}

export function OrderStatusChip({
  status,
  protectedUntil = null,
  estimated = false,
}: OrderStatusChipProps) {
  // Accepted while Steam's protection runs: not stuck, and a rollback is still possible.
  const running = protectedUntil !== null && new Date(protectedUntil).getTime() > Date.now();
  if (protectedUntil !== null && (status === "trade_sent" || (status === "delivered" && running))) {
    const until = `${estimated ? "≈ " : ""}${formatDateTime(protectedUntil)}`;
    return (
      <span
        data-testid="order-status"
        title={`Покупатель принял обмен. Защита Steam до ${until}, затем «получен».`}
        className="bg-info/15 text-info whitespace-nowrap rounded px-2 py-0.5 text-xs font-medium"
      >
        принят, защита до {estimated ? "≈ " : ""}
        {formatDateTime(protectedUntil).slice(0, 5)}
      </span>
    );
  }
  return (
    <StatusChip tone={STATUS_TONE[status]} testId="order-status">
      {STATUS_LABELS[status]}
    </StatusChip>
  );
}

/** «внимание» with the reason on hover and for screen readers; renders nothing without one. */
export function AttentionBadge({ reason }: { reason: AttentionReason | null }) {
  if (reason === null) return null;
  return (
    <span
      data-testid="order-attention"
      title={ATTENTION_LABELS[reason]}
      className="bg-danger/15 text-danger whitespace-nowrap rounded px-2 py-0.5 text-xs font-medium"
    >
      внимание
      <span className="sr-only">: {ATTENTION_LABELS[reason]}</span>
    </span>
  );
}
