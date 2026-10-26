"use client";

import { useEffect } from "react";

import { API_BASE } from "@/lib/api";

/** Counts the view once the article has rendered in a real browser (bots without JS do not). */
export function ViewBeacon({ slug }: { slug: string }) {
  useEffect(() => {
    const url = `${API_BASE}/api/v1/articles/${encodeURIComponent(slug)}/view`;
    if (!navigator.sendBeacon(url)) {
      void fetch(url, { method: "POST", keepalive: true, credentials: "omit" }).catch(
        () => undefined,
      );
    }
  }, [slug]);
  return null;
}
