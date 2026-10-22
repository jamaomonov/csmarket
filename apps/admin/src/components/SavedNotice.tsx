/**
 * «Сохранено · 14:05» after a settings save, announced to screen readers, gone after 6 s. A
 * toast under the top bar: it takes no room in the page, so no empty band waits for it.
 */
import { CheckCircle2 } from "lucide-react";
import { useEffect, useState } from "react";

const SHOWN_MS = 6_000;

export function SavedNotice({ at }: { at: Date | null }) {
  const [shown, setShown] = useState<Date | null>(at);
  useEffect(() => {
    setShown(at);
    if (at === null) return;
    const t = setTimeout(() => {
      setShown(null);
    }, SHOWN_MS);
    return () => {
      clearTimeout(t);
    };
  }, [at]);
  return (
    <div
      role="status"
      className="pointer-events-none fixed inset-x-0 top-[calc(var(--topbar-height)+0.5rem)] z-40 flex justify-center px-4"
    >
      {shown !== null && (
        <p className="border-success/40 bg-surface text-success flex items-center gap-1.5 rounded-full border px-4 py-2 text-sm shadow-lg">
          <CheckCircle2 className="size-4" aria-hidden />
          Сохранено · {shown.toTimeString().slice(0, 5)}
        </p>
      )}
    </div>
  );
}
