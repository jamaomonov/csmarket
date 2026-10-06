import { cn } from "@csmarket/ui";

import { Link } from "@/i18n/navigation";

export interface HistoryFilterOption {
  key: string;
  label: string;
  href: string;
}

interface HistoryFilterProps {
  options: HistoryFilterOption[];
  current: string;
}

/** A segmented row of filter links (shareable URLs) over an account history. */
export function HistoryFilter({ options, current }: HistoryFilterProps) {
  return (
    <div className="bg-surface flex w-fit gap-1 rounded-lg p-1">
      {options.map((o) => (
        <Link
          key={o.key}
          href={o.href}
          aria-current={o.key === current ? "page" : undefined}
          className={cn(
            "rounded-md px-4 py-2 text-[14px] font-medium transition-colors",
            o.key === current ? "bg-surface-2 text-fg" : "text-fg-muted hover:text-fg",
          )}
        >
          {o.label}
        </Link>
      ))}
    </div>
  );
}
