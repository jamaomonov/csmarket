import { type ReactNode, useId } from "react";

import { cn } from "../../lib/cn";

export interface SwitchProps {
  /** What the switch turns on and off («Выкуп»); the accessible name. */
  label: ReactNode;
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  /** The state in words under the label: `[on, off]`, e.g. `["включён", "выключен"]`. */
  states?: readonly [string, string];
  /** A muted line under the state (what it does). */
  hint?: ReactNode;
  disabled?: boolean;
  className?: string;
}

/**
 * An on/off switch (`role="switch"`): the whole row is the button, at least 44 px tall, the
 * track on the left, the label and its state in words beside it. For settings that take effect
 * on their own; a filter option stays a `Checkbox`.
 */
export function Switch({
  label,
  checked,
  onCheckedChange,
  states,
  hint,
  disabled = false,
  className,
}: SwitchProps) {
  const id = useId();
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-labelledby={`${id}-label`}
      aria-describedby={states !== undefined || hint !== undefined ? `${id}-state` : undefined}
      disabled={disabled}
      onClick={() => {
        onCheckedChange(!checked);
      }}
      className={cn(
        "focus-visible:ring-accent focus-visible:ring-offset-bg group flex min-h-11 items-center gap-3 rounded-md text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50",
        className,
      )}
    >
      <span
        aria-hidden
        data-switch={checked ? "on" : "off"}
        className={cn(
          "relative inline-flex h-6 w-10 shrink-0 items-center rounded-full transition-colors",
          checked ? "bg-accent" : "bg-surface-2 border-border-strong border",
        )}
      >
        <span
          className={cn(
            "size-5 rounded-full shadow transition-transform",
            checked ? "bg-accent-fg translate-x-[18px]" : "bg-fg-muted translate-x-0.5",
          )}
        />
      </span>
      <span className="flex min-w-0 flex-col">
        <span id={`${id}-label`} className="text-fg text-body font-medium">
          {label}
        </span>
        {(states !== undefined || hint !== undefined) && (
          <span id={`${id}-state`} className="text-fg-muted text-sm">
            {states !== undefined && (checked ? states[0] : states[1])}
            {states !== undefined && hint !== undefined && " · "}
            {hint}
          </span>
        )}
      </span>
    </button>
  );
}
