"use client";

import { Minus, Plus } from "lucide-react";
import { type ReactNode, useId, useState } from "react";

import { cn } from "../../lib/cn";

interface AccordionProps {
  title: ReactNode;
  defaultOpen?: boolean;
  className?: string;
  children: ReactNode;
}

/** One collapsible section (filters): a header button and its region. */
export function Accordion({ title, defaultOpen = false, className, children }: AccordionProps) {
  const [open, setOpen] = useState(defaultOpen);
  const id = useId();
  return (
    <div className={cn("border-border border-t py-3 first:border-t-0", className)}>
      <h3>
        <button
          id={`${id}-h`}
          type="button"
          aria-expanded={open}
          aria-controls={`${id}-p`}
          onClick={() => {
            setOpen(!open);
          }}
          className="text-fg focus-visible:ring-accent focus-visible:ring-offset-bg flex w-full items-center justify-between rounded-md text-left text-[15px] font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2"
        >
          {title}
          {open ? (
            <Minus className="text-fg-dim size-4" aria-hidden />
          ) : (
            <Plus className="text-fg-dim size-4" aria-hidden />
          )}
        </button>
      </h3>
      {open && (
        <div id={`${id}-p`} role="region" aria-labelledby={`${id}-h`} className="mt-2">
          {children}
        </div>
      )}
    </div>
  );
}
