import { type PaymentStatus } from "./kinds";
import { STATUS_CHIP, STATUS_LABELS } from "./labels";

export function StatusChip({ status }: { status: PaymentStatus }) {
  return (
    <span
      data-testid="payment-status"
      className={`whitespace-nowrap rounded px-2 py-0.5 text-xs ${STATUS_CHIP[status]}`}
    >
      {STATUS_LABELS[status]}
    </span>
  );
}
