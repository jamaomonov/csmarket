import { type AttentionReason, type OrderStatus } from "./kinds";
import { ATTENTION_LABELS, STATUS_CHIP, STATUS_LABELS } from "./labels";

import { formatDateTime } from "@/lib/format";

interface OrderStatusChipProps {
  status: OrderStatus;
  /** When Steam's protection of an accepted trade ends (Skinslink `hold`), if it runs. */
  protectedUntil?: string | null;
}

export function OrderStatusChip({ status, protectedUntil = null }: OrderStatusChipProps) {
  // Accepted, but `delivered` only once the protection ends: not stuck.
  if (status === "trade_sent" && protectedUntil !== null) {
    const until = formatDateTime(protectedUntil);
    return (
      <span
        data-testid="order-status"
        title={`Покупатель принял обмен. Защита Steam до ${until}, затем «получен».`}
        className="bg-success text-success-fg whitespace-nowrap rounded px-2 py-0.5 text-xs"
      >
        принят, защита до {until.slice(0, 5)}
      </span>
    );
  }
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
