import { cn } from "@csmarket/ui";
import { useLocale, useTranslations } from "next-intl";

import { shortDay, type Badge, type Tone } from "@/lib/trade-status";

const TONES: Record<Tone, string> = {
  ok: "text-success bg-success/12",
  wait: "text-warning bg-warning/12",
  run: "text-info bg-info/12",
  bad: "text-danger bg-danger/12",
  muted: "text-fg-dim bg-surface-2",
};

interface StatusBadgeProps {
  badge: Badge;
  className?: string;
}

/** A trade's status as a coloured pill with a dot — the same on the list and the pages. */
export function StatusBadge({ badge, className }: StatusBadgeProps) {
  const t = useTranslations("web");
  const locale = useLocale();
  return (
    <span
      data-testid="status-badge"
      data-tone={badge.tone}
      className={cn(
        "inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-0.5 text-[13px] font-semibold",
        TONES[badge.tone],
        className,
      )}
    >
      <span aria-hidden className="size-1.5 rounded-full bg-current" />
      {t(badge.key, badge.date ? { date: shortDay(locale, badge.date) } : {})}
    </span>
  );
}
