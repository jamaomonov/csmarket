/** «⋯»: rarely used or dangerous actions, out of the way (review §3.5). */
import { MoreHorizontal } from "lucide-react";
import { useEffect, useRef, useState } from "react";

export interface MoreAction {
  key: string;
  label: string;
  onSelect: () => void;
  danger?: boolean;
}

interface MoreMenuProps {
  actions: MoreAction[];
  label?: string;
  /** The «⋯» button's size; 36 px unless a page asks for a thumb-sized one. */
  size?: string;
}

export function MoreMenu({ actions, label = "Ещё действия", size = "size-9" }: MoreMenuProps) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      // A click target is always a DOM node (DOM narrowing).
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => {
      document.removeEventListener("mousedown", close);
    };
  }, [open]);
  return (
    <div
      ref={box}
      className="relative"
      onKeyDown={(e) => {
        if (e.key === "Escape") setOpen(false);
      }}
    >
      <button
        type="button"
        aria-label={label}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => {
          setOpen((v) => !v);
        }}
        className={`border-border hover:bg-surface-2 text-fg-muted grid place-items-center rounded-md border ${size}`}
      >
        <MoreHorizontal className="size-4" aria-hidden />
      </button>
      {open && (
        <div
          role="menu"
          aria-label={label}
          className="border-border bg-surface absolute right-0 top-full z-30 mt-1 min-w-56 rounded-lg border p-1 shadow-[var(--shadow-menu)]"
        >
          {actions.map((a) => (
            <button
              key={a.key}
              type="button"
              role="menuitem"
              onClick={() => {
                setOpen(false);
                a.onSelect();
              }}
              className={`hover:bg-surface-2 block min-h-11 w-full rounded-md px-3 py-2 text-left text-sm sm:min-h-0 ${
                a.danger === true ? "text-danger" : ""
              }`}
            >
              {a.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
