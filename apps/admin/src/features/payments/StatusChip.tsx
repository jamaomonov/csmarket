import { type PaymentStatus } from "./kinds";
import { STATUS_LABELS, STATUS_TONE } from "./labels";

import { StatusChip as Chip } from "@/components/StatusChip";

export function StatusChip({ status }: { status: PaymentStatus }) {
  return (
    <Chip tone={STATUS_TONE[status]} testId="payment-status">
      {STATUS_LABELS[status]}
    </Chip>
  );
}
