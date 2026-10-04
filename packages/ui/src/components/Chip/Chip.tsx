import { cva } from "class-variance-authority";
import { type ButtonHTMLAttributes, forwardRef, type ReactNode } from "react";

import { cn } from "../../lib/cn";

/** A filter toggle: surface by default, green when active. Links reuse `chipVariants`. */
export const chipVariants = cva(
  [
    "inline-flex shrink-0 items-center gap-2 whitespace-nowrap rounded-md px-3.5 py-2 text-[13px] font-medium",
    "transition-colors duration-(--duration-fast)",
    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg",
  ],
  {
    variants: {
      active: {
        true: "bg-accent text-accent-fg font-semibold",
        false: "bg-surface text-fg-muted hover:bg-surface-2 hover:text-fg",
      },
    },
    defaultVariants: { active: false },
  },
);

export interface ChipProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  active?: boolean;
  icon?: ReactNode;
}

export const Chip = forwardRef<HTMLButtonElement, ChipProps>(
  ({ active = false, icon, className, children, type = "button", ...props }, ref) => (
    <button
      ref={ref}
      type={type}
      aria-pressed={active}
      className={cn(chipVariants({ active }), className)}
      {...props}
    >
      {icon}
      {children}
    </button>
  ),
);
Chip.displayName = "Chip";
