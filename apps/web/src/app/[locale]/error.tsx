"use client";

import { useTranslations } from "next-intl";
import { useEffect } from "react";

export default function LocaleError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  const t = useTranslations("web.error");
  const common = useTranslations("common");
  useEffect(() => {
    console.error("route error", error.digest ?? error.message);
  }, [error]);
  return (
    <main className="mx-auto flex min-h-screen max-w-xl flex-col items-center justify-center px-6 text-center">
      <h1 className="text-2xl font-bold">{t("title")}</h1>
      <p className="text-fg-muted mt-3">{t("body")}</p>
      <button
        type="button"
        onClick={reset}
        className="bg-accent text-accent-fg mt-8 rounded-md px-5 py-3 font-semibold"
      >
        {common("actions.retry")}
      </button>
    </main>
  );
}
