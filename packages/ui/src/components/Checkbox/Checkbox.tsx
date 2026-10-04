import { Check } from "lucide-react";
import { forwardRef, type InputHTMLAttributes, type ReactNode } from "react";

import { cn } from "../../lib/cn";

/** The visual box alone — for filter options that are links, not inputs. */
export function CheckMark({ checked }: { checked: boolean }) {
  return (
    <span
      aria-hidden
      data-check={checked ? "on" : "off"}
      className={cn(
        "flex size-4 shrink-0 items-center justify-center rounded-[5px]",
        checked ? "bg-accent text-accent-fg" : "bg-surface-2",
      )}
    >
      {checked && <Check className="size-3" strokeWidth={3.5} />}
    </span>
  );
}

interface CheckboxProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "type"> {
  children: ReactNode;
}

export const Checkbox = forwardRef<HTMLInputElement, CheckboxProps>(
  ({ children, className, ...props }, ref) => (
    <label
      className={cn(
        "text-fg-muted flex cursor-pointer items-center gap-2.5 text-[14px]",
        className,
      )}
    >
      <input
        ref={ref}
        type="checkbox"
        className="bg-surface-2 checked:bg-accent focus-visible:ring-accent peer size-4 appearance-none rounded-[5px] focus-visible:outline-none focus-visible:ring-2"
        {...props}
      />
      {children}
    </label>
  ),
);
Checkbox.displayName = "Checkbox";
