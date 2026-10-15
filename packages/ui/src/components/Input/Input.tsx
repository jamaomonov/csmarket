import { forwardRef, type InputHTMLAttributes } from "react";

import { cn } from "../../lib/cn";

export const inputClass =
  "h-10 w-full rounded-md border border-border bg-surface px-3 text-body text-fg placeholder:text-fg-dim transition-colors hover:border-border-strong focus-visible:border-accent/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/20";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  ({ className, ...props }, ref) => (
    <input ref={ref} className={cn(inputClass, className)} {...props} />
  ),
);
Input.displayName = "Input";
