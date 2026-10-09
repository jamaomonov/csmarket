"use client";

/** Fades `.rv` blocks in as they scroll into view; marks the root `.js` so no-JS shows all. */
import { useEffect } from "react";

export function Reveal({ rootId }: { rootId: string }) {
  useEffect(() => {
    const root = document.getElementById(rootId);
    if (!root) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    root.classList.add("js");
    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (e.isIntersecting) {
            e.target.classList.add("in");
            io.unobserve(e.target);
          }
        }
      },
      { rootMargin: "0px 0px -8% 0px" },
    );
    root.querySelectorAll(".rv").forEach((el) => {
      io.observe(el);
    });
    return () => {
      io.disconnect();
    };
  }, [rootId]);
  return null;
}
