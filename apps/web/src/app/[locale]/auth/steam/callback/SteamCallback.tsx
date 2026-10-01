"use client";

import { useSearchParams } from "next/navigation";
import { hasLocale, useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";

import { useRouter } from "@/i18n/navigation";
import { routing } from "@/i18n/routing";
import { useAuth } from "@/lib/auth";

/** Steam returns here (ruling P1); we hand the openid.* params to the API. */
export function SteamCallback() {
  const t = useTranslations("web.auth.callback");
  const search = useSearchParams();
  const router = useRouter();
  const { completeSteamSignIn, signInHref } = useAuth();
  const [failed, setFailed] = useState(false);
  const started = useRef(false);
  // Frozen on first render: stripping the query below re-renders with empty search
  // params, which would otherwise send the retry link back to the default locale.
  const [locale] = useState(() => {
    const requested = search.get("locale");
    return hasLocale(routing.locales, requested) ? requested : routing.defaultLocale;
  });

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    const params: Record<string, string> = {};
    search.forEach((value, key) => {
      if (key.startsWith("openid.")) params[key] = value;
    });
    // The assertion carries the Steam ID; keep it out of history and referrers.
    window.history.replaceState(null, "", window.location.pathname);
    completeSteamSignIn(params)
      .then(() => {
        router.replace("/account", { locale });
      })
      .catch(() => {
        setFailed(true);
      });
  }, [search, completeSteamSignIn, router, locale]);

  return (
    <main className="mx-auto flex min-h-[60vh] max-w-xl flex-col items-center justify-center px-6 text-center">
      {failed ? (
        <>
          <h1 className="text-xl font-bold">{t("failed")}</h1>
          <a
            href={signInHref(locale)}
            className="bg-accent text-accent-fg mt-6 rounded-md px-5 py-3 font-semibold"
          >
            {t("retry")}
          </a>
        </>
      ) : (
        <p className="text-fg-muted">{t("working")}</p>
      )}
    </main>
  );
}
