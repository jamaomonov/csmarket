/** A top-up's status as a coloured chip. */
import { type TopupStatus } from "./api";
import { topupStatusLabel } from "./labels";

import { StatusChip, type Tone } from "@/components/StatusChip";

const TONES: Record<TopupStatus, Tone> = {
  pending: "progress",
  succeeded: "success",
  expired: "muted",
  reversed: "danger",
};

export function TopupStatusChip({ status }: { status: TopupStatus }) {
  return <StatusChip tone={TONES[status]}>{topupStatusLabel(status)}</StatusChip>;
}
