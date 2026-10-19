/**
 * The admin's dialog shell (review §4.9): backdrop, a titled card. Esc closes it wherever focus
 * is; focus moves into it (the first field, else the first button), Tab stays inside, and goes
 * back to what opened it on close; the page behind does not scroll.
 */
import { type ReactNode, useEffect, useId, useRef } from "react";

interface ModalProps {
  title: ReactNode;
  description?: ReactNode;
  onClose: () => void;
  /** No close while a request runs. */
  busy?: boolean;
  children: ReactNode;
  testId?: string;
  wide?: boolean;
}

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

function focusables(root: HTMLElement): HTMLElement[] {
  return [...root.querySelectorAll<HTMLElement>(FOCUSABLE)];
}

export function Modal({
  title,
  description,
  onClose,
  busy = false,
  children,
  testId,
  wide,
}: ModalProps) {
  const titleId = useId();
  const card = useRef<HTMLDivElement>(null);
  const closeRef = useRef({ onClose, busy });
  closeRef.current = { onClose, busy };

  useEffect(() => {
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const root = card.current;
    if (root !== null && !root.contains(document.activeElement)) {
      const field = root.querySelector<HTMLElement>("input, select, textarea");
      (field ?? focusables(root)[0] ?? root).focus();
    }
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !closeRef.current.busy) {
        closeRef.current.onClose();
        return;
      }
      if (e.key !== "Tab" || card.current === null) return;
      const items = focusables(card.current);
      const first = items[0];
      const last = items[items.length - 1];
      if (first === undefined || last === undefined) return;
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = overflow;
      opener?.focus();
    };
  }, []);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      data-testid={testId}
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/60 p-0 sm:items-center sm:p-4"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget && !busy) onClose();
      }}
    >
      <div
        ref={card}
        tabIndex={-1}
        className={`border-border bg-surface max-h-[90vh] w-full space-y-4 overflow-y-auto rounded-t-xl border p-5 shadow-[var(--shadow-menu)] outline-none sm:rounded-xl ${
          wide === true ? "sm:max-w-2xl" : "sm:max-w-md"
        }`}
      >
        <div className="space-y-1">
          <h2 id={titleId} className="text-lg font-semibold">
            {title}
          </h2>
          {description !== undefined && <p className="text-fg-muted text-sm">{description}</p>}
        </div>
        {children}
      </div>
    </div>
  );
}
