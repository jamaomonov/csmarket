/** The admin's dialog shell (review §4.9): backdrop, Esc to close, a titled card. */
import { type ReactNode, useId } from "react";

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
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      data-testid={testId}
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/60 p-0 sm:items-center sm:p-4"
      onKeyDown={(e) => {
        if (e.key === "Escape" && !busy) onClose();
      }}
      onMouseDown={(e) => {
        if (e.target === e.currentTarget && !busy) onClose();
      }}
    >
      <div
        className={`border-border bg-surface max-h-[90vh] w-full space-y-4 overflow-y-auto rounded-t-xl border p-5 shadow-[var(--shadow-menu)] sm:rounded-xl ${
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
