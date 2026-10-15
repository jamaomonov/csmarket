import { forwardRef, type SelectHTMLAttributes } from "react";

import { cn } from "../../lib/cn";

export const selectClass =
  "h-10 appearance-none rounded-md border border-border bg-surface pl-3 pr-9 text-body font-medium text-fg transition-colors hover:border-border-strong focus-visible:border-accent/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/20 bg-[url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%23A4ABB8' stroke-width='2.5'%3E%3Cpath d='m6 9 6 6 6-6'/%3E%3C/svg%3E\")] bg-[length:12px] bg-[right_12px_center] bg-no-repeat";

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(
  ({ className, ...props }, ref) => (
    <select ref={ref} className={cn(selectClass, className)} {...props} />
  ),
);
Select.displayName = "Select";
