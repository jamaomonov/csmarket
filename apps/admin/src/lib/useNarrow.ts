/** Whether the screen is narrower than `md` (768 px); `false` where `matchMedia` is missing. */
import { useEffect, useState } from "react";

const QUERY = "(max-width: 767px)";

function narrowNow(): boolean {
  return typeof window.matchMedia === "function" && window.matchMedia(QUERY).matches;
}

export function useNarrow(): boolean {
  const [narrow, setNarrow] = useState(narrowNow);
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const media = window.matchMedia(QUERY);
    const sync = () => {
      setNarrow(media.matches);
    };
    media.addEventListener("change", sync);
    return () => {
      media.removeEventListener("change", sync);
    };
  }, []);
  return narrow;
}
