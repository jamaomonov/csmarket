/** A status chip with a tone (spec: admin UX review §4.2). Green accent is never a status. */
import { type ReactNode } from "react";

export type Tone = "neutral" | "progress" | "info" | "success" | "danger" | "muted";

const TONE_CLASS: Record<Tone, string> = {
  neutral: "bg-surface-2 text-fg",
  progress: "bg-warning/15 text-warning",
  info: "bg-info/15 text-info",
  success: "bg-success/15 text-success",
  danger: "bg-danger/15 text-danger",
  muted: "bg-surface-2 text-fg-dim",
};

interface StatusChipProps {
  tone: Tone;
  children: ReactNode;
  /** A second line under the chip (a hold's countdown, a refund's reason). */
  sub?: ReactNode;
  title?: string;
  testId?: string;
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
        <span className="text-fg-dim whitespace-nowrap text-[11px]">{sub}</span>
      )}
    </span>
  );
}
