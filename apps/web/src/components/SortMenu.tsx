"use client";

import { Dropdown, type DropdownItem } from "@csmarket/ui";
import { Check, ChevronDown, type LucideIcon } from "lucide-react";

import { AppLink } from "./header/AccountMenu";

export interface SortOption<T extends string> {
  value: T;
  label: string;
  icon: LucideIcon;
}

interface SortMenuProps<T extends string> {
  /** What the control is («Сортировка»), for screen readers. */
  label: string;
  options: readonly SortOption<T>[];
  value: T;
  /** A link per option (the market, where the sort lives in the URL)… */
  hrefFor?: (value: T) => string;
  /** …or a callback (the sale page, where it is local state). */
  onPick?: (value: T) => void;
  className?: string;
}

/**
 * The sort as our own menu instead of the system select: the trigger shows the current
 * order with its icon, each option has one, and the chosen one is ticked. Keyboard and
 * screen-reader behaviour come from `Dropdown` (a WAI-ARIA menu).
 */
export function SortMenu<T extends string>({
  label,
  options,
  value,
  hrefFor,
  onPick,
  className,
}: SortMenuProps<T>) {
  const current = options.find((o) => o.value === value) ?? options[0];
  const items: DropdownItem[] = options.map((o) => ({
    key: o.value,
    label: o.label,
    icon: <o.icon className="text-fg-muted size-4" aria-hidden />,
    current: o.value === value,
    ...(o.value === value ? { meta: <Check className="text-accent size-4" aria-hidden /> } : {}),
    ...(hrefFor ? { href: hrefFor(o.value) } : {}),
    ...(onPick
      ? {
          onSelect: () => {
            onPick(o.value);
          },
        }
      : {}),
  }));
  const Icon = current?.icon;
  return (
    <div className={className}>
      <Dropdown
        label={
          <>
            {Icon && <Icon className="text-fg-muted size-4 shrink-0" aria-hidden />}
            <span className="min-w-0 flex-1 truncate text-left">{current?.label}</span>
            <ChevronDown className="text-fg-dim size-4 shrink-0" aria-hidden />
          </>
        }
        triggerLabel={current ? `${label}: ${current.label}` : label}
        triggerClassName="border-border hover:border-border-strong h-10 w-full border font-medium transition-colors"
        items={items}
        align="end"
        LinkComponent={AppLink}
      />
    </div>
  );
}
