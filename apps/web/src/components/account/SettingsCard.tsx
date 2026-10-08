import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

interface SettingsCardProps {
  icon: LucideIcon;
  title: ReactNode;
  hint?: ReactNode;
  /** On the right of the row (an «Изменить» button, a badge). */
  aside?: ReactNode;
  children?: ReactNode;
}

/** One row of the profile's settings: a round icon, a title with its value or hint, an action. */
export function SettingsCard({ icon: Icon, title, hint, aside, children }: SettingsCardProps) {
  return (
    <section className="border-border flex items-start gap-4 border-b py-5 last:border-b-0">
      <span className="bg-surface text-fg-muted grid size-12 shrink-0 place-items-center rounded-full">
        <Icon className="size-5" aria-hidden />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h3 className="flex items-center gap-2 text-[17px] font-semibold">{title}</h3>
            {hint ? <div className="text-fg-muted mt-1 text-sm">{hint}</div> : null}
          </div>
          {aside ? <div className="shrink-0">{aside}</div> : null}
        </div>
        {children}
      </div>
    </section>
  );
}
