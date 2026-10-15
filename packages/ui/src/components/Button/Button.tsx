import { cva, type VariantProps } from "class-variance-authority";
import { type ButtonHTMLAttributes, forwardRef } from "react";

import { cn } from "../../lib/cn";

/**
 * Four intentions: `primary` (the page's one main action), `secondary` (outlined
 * surface), `ghost` (transparent, reveals a tile on hover) and `danger`. Active
 * state is deliberate on every variant so a tap feels registered before the
 * route changes.
 */
export const buttonVariants = cva(
  [
    "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-lg text-small font-medium",
    "transition-[background-color,border-color,color,box-shadow] duration-(--duration-fast)",
    "disabled:pointer-events-none disabled:opacity-50",
    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg",
  ],
  {
    variants: {
      variant: {
        primary:
          "bg-accent text-accent-fg font-semibold hover:bg-accent-hover active:bg-accent-active disabled:bg-surface-2 disabled:text-fg-dim disabled:opacity-100",
        secondary:
          "bg-surface text-fg border border-border-strong hover:bg-surface-2 active:bg-surface-hover",
        ghost: "text-fg-muted hover:bg-surface hover:text-fg active:bg-surface-2",
        danger: "bg-danger text-danger-fg font-semibold hover:opacity-90 active:opacity-100",
      },
      size: { sm: "h-8 px-3", md: "h-10 px-4", lg: "h-12 px-6 text-lead" },
    },
    defaultVariants: { variant: "primary", size: "md" },
  },
);

export interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof buttonVariants> {}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, type = "button", ...props }, ref) => (
    <button
      ref={ref}
      type={type}
      className={cn(buttonVariants({ variant, size }), className)}
      {...props}
    />
  ),
);

Button.displayName = "Button";
