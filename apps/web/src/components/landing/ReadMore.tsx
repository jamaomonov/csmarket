"use client";

/** Unfolds the SEO text on phones; the full text is always in the HTML. */
import { type ReactNode, useState } from "react";

import { cx } from "./format";

export function ReadMore({ label, children }: { label: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <div className={cx("prose", open && "open")}>{children}</div>
      {!open && (
        <button
          className="readmore"
          type="button"
          aria-expanded={open}
          onClick={() => {
            setOpen(true);
          }}
        >
          {label}
        </button>
      )}
    </>
  );
}
