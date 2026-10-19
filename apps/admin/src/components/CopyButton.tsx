/** «Копировать» next to a value an admin pastes elsewhere (an id, a link). */
import { useState } from "react";

import { copyText } from "@/features/sales/clipboard";

export function CopyButton({ value, label }: { value: string; label: string }) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    // A refused copy just leaves the button idle; the value stays selectable on the page.
    void copyText(value).then(setCopied);
  };
  return (
    <button
      type="button"
      aria-label={label}
      onClick={copy}
      className="text-accent ml-2 whitespace-nowrap text-xs hover:underline"
    >
      {copied ? "Скопировано" : "Копировать"}
    </button>
  );
}
