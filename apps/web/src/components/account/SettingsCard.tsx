import { cn } from "@csmarket/ui";

import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

interface SettingsCardProps {
  icon: LucideIcon;
  title: ReactNode;
  /** The saved value or what the setting is for, under the title. */
  hint?: ReactNode;
  /** On the right of the row (an «Изменить» button, a badge). */
  aside?: ReactNode;
  /** The icon tile turns green: the setting is done. */
  done?: boolean;
  children?: ReactNode;
}

/**
 * One row of a settings panel: an icon tile, a title with its value or hint, an action on the
 * right. Rows sit inside a `SettingsPanel` and are divided by a hairline.
 */
export function SettingsCard({
  icon: Icon,
  title,
  hint,
  aside,
  done = false,
  children,
}: SettingsCardProps) {
  return (
    <section className="border-border flex items-start gap-4 border-t px-4 py-4 first:border-t-0 sm:px-5 sm:py-5">
      <span
        className={cn(
          "grid size-10 shrink-0 place-items-center rounded-lg sm:size-11",
          done ? "bg-accent-subtle text-accent" : "bg-surface-2 text-fg-muted",
        )}
      >
        <Icon className="size-5" aria-hidden />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex min-h-10 items-center justify-between gap-3 sm:min-h-11">
          <div className="min-w-0">
            <h3 className="flex items-center gap-1.5 text-[15px] font-semibold">{title}</h3>
            {hint ? <div className="text-fg-muted mt-0.5 text-sm">{hint}</div> : null}
          </div>
          {aside ? <div className="shrink-0">{aside}</div> : null}
        </div>
        {children}
      </div>
    </section>
  );
}

interface SettingsPanelProps {
  title: ReactNode;
  /** A line under the title, quieter. */
  description?: ReactNode;
  className?: string;
  children: ReactNode;
}

/** A titled surface that holds settings rows. */
export function SettingsPanel({ title, description, className, children }: SettingsPanelProps) {
  return (
    <section className={cn("bg-surface overflow-hidden rounded-xl", className)}>
      <header className="border-border border-b px-4 py-3.5 sm:px-5">
        <h2 className="text-fg-dim text-xs font-semibold uppercase tracking-wider">{title}</h2>
        {description ? <p className="text-fg-muted mt-1 text-sm">{description}</p> : null}
      </header>
      {children}
    </section>
  );
}

type NoticeTone = "ok" | "bad" | "warn" | "muted";

const NOTICE: Record<NoticeTone, string> = {
  ok: "border-success/30 bg-success/10 text-success",
  bad: "border-danger/30 bg-danger/10 text-danger",
  warn: "border-warning/30 bg-warning/10 text-fg",
  muted: "border-border bg-bg/40 text-fg-muted",
};

interface NoticeProps {
  tone: NoticeTone;
  role?: "status" | "alert";
  children: ReactNode;
}

/** A short tinted note under a row: a verdict, an outcome, a pending confirmation. */
export function Notice({ tone, role, children }: NoticeProps) {
  return (
    <div role={role} className={cn("mt-3 rounded-lg border px-3 py-2.5 text-sm", NOTICE[tone])}>
      {children}
    </div>
  );
}
