"use client";

import Script from "next/script";
import { useEffect, useState } from "react";

import { GA_ID, gaEnabled, track, type GaEvent } from "@/lib/analytics";

/**
 * The GA4 tag, loaded after the page is interactive and only on csmarket.uz. Decided after
 * mount so the server HTML is the same everywhere.
 */
export function Analytics() {
  const [on, setOn] = useState(false);
  useEffect(() => {
    setOn(gaEnabled(window.location.hostname));
  }, []);
  if (!on) return null;
  return (
    <>
      <Script
        src={`https://www.googletagmanager.com/gtag/js?id=${GA_ID}`}
        strategy="afterInteractive"
      />
      <Script id="ga4-init" strategy="afterInteractive">
        {`window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments);}gtag('js',new Date());gtag('config','${GA_ID}');`}
      </Script>
    </>
  );
}

/** Sends one event when it mounts: for a server page that has no client code of its own. */
export function TrackEvent({ event }: { event: GaEvent }) {
  const key = JSON.stringify(event);
  useEffect(() => {
    track(event);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- re-send only when the event changes
  }, [key]);
  return null;
}
