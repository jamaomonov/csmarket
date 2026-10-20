"use client";

import { useTranslations } from "next-intl";

import { Link } from "@/i18n/navigation";
import { fixFor } from "@/lib/trade-link";

interface TradeLinkFixProps {
  /** Copy key under `web.account.tradeLink.status`: why the link cannot take the skin. */
  reason: string;
  checking: boolean;
  onRecheck: () => void;
}

/** Why the trade link is refused, where to fix it, and «Проверить снова» — in the buy form. */
export function TradeLinkFix({ reason, checking, onRecheck }: TradeLinkFixProps) {
  const t = useTranslations("web.buy.fix");
  const tl = useTranslations("web.account.tradeLink.status");
  const fix = fixFor(reason);
  return (
    <div
      role="alert"
      className="border-danger/40 bg-danger/10 flex flex-col gap-3 rounded-lg border p-3"
    >
      <p className="text-danger text-sm">{tl(reason)}</p>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm font-semibold">
        {fix !== null && (
          <a
            href={fix.href}
            target="_blank"
            rel="noopener noreferrer"
            className="text-accent hover:underline"
          >
            {t(fix.label)}
          </a>
        )}
        {reason === "invalid" && (
          <Link href="/account" className="text-accent hover:underline">
            {t("editLink")}
          </Link>
        )}
        <button
          type="button"
          disabled={checking}
          onClick={onRecheck}
          className="text-fg hover:text-accent disabled:text-fg-dim underline-offset-2 hover:underline"
        >
          {checking ? t("checking") : t("recheck")}
        </button>
      </div>
    </div>
  );
}
