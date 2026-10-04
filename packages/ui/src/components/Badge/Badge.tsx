import { cva } from "class-variance-authority";

import { cn } from "../../lib/cn";

import type { ReactNode } from "react";

const badgeVariants = cva(
  "inline-flex items-center rounded-sm px-1.5 py-0.5 text-[11px] font-semibold",
  {
    variants: {
      tone: {
        accent: "bg-accent-subtle text-accent",
        neutral: "bg-surface-2 text-fg-muted",
        danger: "bg-danger/15 text-danger",
      },
    },
    defaultVariants: { tone: "accent" },
  },
);

interface BadgeProps {
  tone?: "accent" | "neutral" | "danger";
  className?: string;
  children: ReactNode;
}

/** A small label: a discount, a wear code, a state. */
export function Badge({ tone = "accent", className, children }: BadgeProps) {
  return <span className={cn(badgeVariants({ tone }), className)}>{children}</span>;
}
