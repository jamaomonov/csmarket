/** One sentence and an optional action, for an empty list or a failed load (review §4.11). */
import { type ReactNode } from "react";

interface EmptyStateProps {
  children: ReactNode;
  action?: ReactNode;
  tone?: "muted" | "danger";
}

export function EmptyState({ children, action, tone = "muted" }: EmptyStateProps) {
  return (
    <div
      role={tone === "danger" ? "alert" : undefined}
      className="flex flex-col items-center gap-2 px-4 py-6 text-center text-sm"
    >
      <p className={tone === "danger" ? "text-danger" : "text-fg-muted"}>{children}</p>
      {action}
    </div>
  );
}
