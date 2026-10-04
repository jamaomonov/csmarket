import { forwardRef, type InputHTMLAttributes } from "react";

import { cn } from "../../lib/cn";

export const inputClass =
  "h-10 w-full rounded-md bg-surface-2 px-3 text-[14px] text-fg placeholder:text-fg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  ({ className, ...props }, ref) => (
    <input ref={ref} className={cn(inputClass, className)} {...props} />
  ),
);
Input.displayName = "Input";
