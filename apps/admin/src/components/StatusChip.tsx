/**
 * The base chip: a tone and a word (admin UX review §4.2). Green accent is never a status. A
 * status of a thing (an order, a payment, a payout…) is `Status`, which reads its word and tone
 * from the one dictionary (`lib/dictionary.ts`); this base is for chips that are not statuses
 * («админ», «API», a payout's risk flag).
 */
import { type ReactNode } from "react";

export type Tone = "neutral" | "progress" | "info" | "success" | "danger" | "muted";

const TONE_CLASS: Record<Tone, string> = {
  neutral: "bg-surface-2 text-fg",
  progress: "bg-warning/15 text-warning",
  info: "bg-info/15 text-info",
  success: "bg-success/15 text-success",
  danger: "bg-danger/15 text-danger",
  // fg-muted: fg-dim reads only ~4.0:1 on surface-2 (tokens.css).
  muted: "bg-surface-2 text-fg-muted",
};

interface StatusChipProps {
  tone: Tone;
  children: ReactNode;
  /** A second line under the chip (a hold's countdown, a refund's reason). */
  sub?: ReactNode;
  title?: string | undefined;
  testId?: string | undefined;
}

export function StatusChip({ tone, children, sub, title, testId }: StatusChipProps) {
  return (
    <span className="inline-flex flex-col items-start gap-0.5">
      <span
        data-testid={testId}
        title={title}
        className={`whitespace-nowrap rounded px-2 py-0.5 text-xs font-medium ${TONE_CLASS[tone]}`}
      >
        {children}
      </span>
      {sub !== undefined && sub !== null && (
        <span className="text-fg-dim text-meta whitespace-nowrap">{sub}</span>
      )}
    </span>
  );
}
