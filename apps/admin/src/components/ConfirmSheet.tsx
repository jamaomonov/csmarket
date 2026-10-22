/**
 * The confirm step of a money action. On a phone it is a bottom sheet (`Modal`), so the sticky
 * action bar never covers it and the main answer spans the width; on desktop it stays inline
 * under the buttons, scrolls into view and puts the focus on its first field. Either way the
 * content sits in a group labelled «Подтверждение».
 */
import { type ReactNode, useEffect, useRef } from "react";

import { Modal } from "./Modal";

import { useNarrow } from "@/lib/useNarrow";

/** An outlined red button: a dangerous action that is not the step's main one. */
export const DANGER_OUTLINE = "border-danger/60 text-danger hover:bg-danger/10";

/** The confirm's own buttons: full width and the main one on top on a phone, a row on desktop. */
export const CONFIRM_BUTTONS =
  "flex flex-col-reverse gap-2 sm:flex-row [&>button]:w-full sm:[&>button]:w-auto";

interface ConfirmSheetProps {
  /** The sheet's title on a phone. */
  title: string;
  onClose: () => void;
  /** No close while the request runs. */
  busy?: boolean;
  testId?: string;
  children: ReactNode;
}

const FIELD = "textarea, input, select";

export function ConfirmSheet({
  title,
  onClose,
  busy = false,
  testId,
  children,
}: ConfirmSheetProps) {
  const narrow = useNarrow();
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const root = box.current;
    if (narrow || root === null) return;
    // jsdom has no scrollIntoView.
    if (typeof root.scrollIntoView === "function") {
      root.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
    const field = root.querySelector<HTMLElement>(FIELD);
    field?.focus({ preventScroll: true });
  }, [narrow]);
  const group = (
    <div
      ref={box}
      role="group"
      aria-label="Подтверждение"
      data-testid={testId}
      className={
        narrow
          ? "flex flex-col gap-3"
          : "border-border bg-surface flex scroll-mb-24 flex-col gap-3 rounded-lg border p-4"
      }
    >
      {children}
    </div>
  );
  if (!narrow) return group;
  return (
    <Modal title={title} onClose={onClose} busy={busy}>
      {group}
    </Modal>
  );
}
