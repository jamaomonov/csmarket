/** «внимание» with the reason on hover and for screen readers; renders nothing without one. */
import { type AttentionReason } from "./kinds";

import { StatusChip } from "@/components/StatusChip";
import { reasonText } from "@/lib/dictionary";

export function AttentionBadge({ reason }: { reason: AttentionReason | null }) {
  if (reason === null) return null;
  const text = reasonText("orderAttention", reason);
  return (
    <StatusChip tone="danger" title={text} testId="order-attention">
      внимание
      <span className="sr-only">: {text}</span>
    </StatusChip>
  );
}
