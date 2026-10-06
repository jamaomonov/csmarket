import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

interface SettingsCardProps {
  icon: LucideIcon;
  title: ReactNode;
  hint?: ReactNode;
  /** Beside the title on wide screens (a badge, a button). */
  aside?: ReactNode;
  children?: ReactNode;
}

/** One row of «Ваш аккаунт»: an icon, a title with its hint, an optional action, a body. */
export function SettingsCard({ icon: Icon, title, hint, aside, children }: SettingsCardProps) {
  return (
    <section className="bg-surface rounded-xl p-5">
      <div className="flex items-start gap-4">
        <span className="bg-surface-2 text-fg-muted grid size-10 shrink-0 place-items-center rounded-full">
          <Icon className="size-[18px]" aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
            <h3 className="font-semibold">{title}</h3>
            {aside}
          </div>
          {hint ? <div className="text-fg-muted mt-0.5 text-sm">{hint}</div> : null}
          {children}
        </div>
      </div>
    </section>
  );
}
