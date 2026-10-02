import { type AttentionReason, type OrderStatus } from "./kinds";
import { ATTENTION_LABELS, STATUS_CHIP, STATUS_LABELS } from "./labels";

export function OrderStatusChip({ status }: { status: OrderStatus }) {
  return (
    <span
      data-testid="order-status"
      className={`whitespace-nowrap rounded px-2 py-0.5 text-xs ${STATUS_CHIP[status]}`}
    >
      {STATUS_LABELS[status]}
    </span>
  );
}

/** «внимание» with the reason on hover and for screen readers; renders nothing without one. */
export function AttentionBadge({ reason }: { reason: AttentionReason | null }) {
  if (reason === null) return null;
  return (
    <span
      data-testid="order-attention"
      title={ATTENTION_LABELS[reason]}
      className="bg-danger text-danger-fg whitespace-nowrap rounded px-2 py-0.5 text-xs"
    >
      внимание
      <span className="sr-only">: {ATTENTION_LABELS[reason]}</span>
    </span>
  );
}
