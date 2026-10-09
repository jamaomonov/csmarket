/** Detail pages (review §4.8): titled sections in a two-column grid, label/value rows. */
import { type ReactNode } from "react";

export function DetailGrid({ main, side }: { main: ReactNode; side?: ReactNode }) {
  return (
    <div className="grid gap-4 lg:grid-cols-[2fr_1fr]">
      <div className="min-w-0 space-y-4">{main}</div>
      {side !== undefined && <div className="min-w-0 space-y-4">{side}</div>}
    </div>
  );
}

interface SectionProps {
  title: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  label?: string;
}

export function Section({ title, actions, children, label }: SectionProps) {
  return (
    <section
      aria-label={label ?? (typeof title === "string" ? title : undefined)}
      className="border-border bg-surface rounded-lg border"
    >
      <div className="border-border flex items-center justify-between gap-2 border-b px-4 py-2.5">
        <h2 className="text-[15px] font-semibold">{title}</h2>
        {actions}
      </div>
      <div className="p-4">{children}</div>
    </section>
  );
}

/** A label/value row: label 140 px muted, value wraps (one column on phones). */
export function Row({ label, children }: { label: ReactNode; children: ReactNode }) {
  return (
    <div className="grid grid-cols-1 gap-0.5 py-1 text-sm sm:grid-cols-[140px_1fr] sm:gap-3">
      <dt className="text-fg-muted">{label}</dt>
      <dd className="min-w-0 break-words">{children}</dd>
    </div>
  );
}

/** A red banner at the top of a detail page (an open attention, a ban). */
export function Banner({
  children,
  tone = "danger",
}: {
  children: ReactNode;
  tone?: "danger" | "info";
}) {
  return (
    <div
      role="status"
      className={`rounded-lg border px-4 py-3 text-sm ${
        tone === "danger"
          ? "border-danger/40 bg-danger/10 text-danger"
          : "border-info/40 bg-info/10 text-info"
      }`}
    >
      {children}
    </div>
  );
}
