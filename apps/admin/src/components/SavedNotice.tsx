/** «Сохранено · 14:05» after a settings save, announced to screen readers, gone after 6 s. */
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
    <p role="status" className="text-success flex min-h-5 items-center gap-1.5 text-sm">
      {shown !== null && (
        <>
          <CheckCircle2 className="size-4" aria-hidden />
          Сохранено · {shown.toTimeString().slice(0, 5)}
        </>
      )}
    </p>
  );
}
