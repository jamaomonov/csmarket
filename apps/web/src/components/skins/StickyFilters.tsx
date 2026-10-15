"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";

/** Below the sticky header (64 px) with a little air. */
const HEADER_GAP = 80;
const BOTTOM_GAP = 16;

/**
 * The filter column, held in view without a scrollbar of its own: it scrolls with the page
 * until its last section (StatTrak™) is on screen, then stays. When it fits the screen it
 * sticks under the header; when it is taller, its `top` goes negative by the overflow, so
 * the bottom is what sticks. Re-measured whenever a section opens or the window resizes.
 */
export function StickyFilters({ children }: { children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  const [top, setTop] = useState(HEADER_GAP);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => {
      setTop(Math.min(HEADER_GAP, window.innerHeight - el.offsetHeight - BOTTOM_GAP));
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    window.addEventListener("resize", measure);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, []);

  return (
    <div ref={ref} className="sticky pb-4" style={{ top }}>
      {children}
    </div>
  );
}
