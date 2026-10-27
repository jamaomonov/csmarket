"use client";

import { useEffect } from "react";

import { REF_PARAM, REF_PATTERN, rememberVisit, withoutRef } from "@/lib/referrals";

/** A partner's link (`?ref=<code>` on any page): remembered for the sign-in, then taken out of
 * the address so it is not shared further or indexed. */
export function RefCapture() {
  useEffect(() => {
    const { pathname, search, hash } = window.location;
    // The API lowercases a code; a link shared as `?ref=ZufarMax` still counts.
    const code = new URLSearchParams(search).get(REF_PARAM)?.trim().toLowerCase() ?? null;
    if (code === null) return;
    if (REF_PATTERN.test(code)) rememberVisit(code);
    window.history.replaceState(window.history.state, "", pathname + withoutRef(search) + hash);
  }, []);
  return null;
}
