"use client";

import { X } from "lucide-react";
import { useTranslations } from "next-intl";

import { Stars } from "./Stars";

import type { PendingDeal } from "@/lib/reviews";

interface ReviewStripProps {
  deal: PendingDeal;
  /** A star: open the modal with it chosen. */
  onRate: (rating: number) => void;
  /** «Не сейчас»: ask again in 3 days. */
  onLater: () => void;
  /** ×: never ask about this deal again. */
  onDismiss: () => void;
}

/** The bottom reminder: «Как прошла покупка <скин>?» with stars; not a modal. */
export function ReviewStrip({ deal, onRate, onLater, onDismiss }: ReviewStripProps) {
  const t = useTranslations("web.reviews.strip");
  return (
    <aside
      aria-label={t("label")}
      className="bg-surface-solid border-border fixed inset-x-0 bottom-0 z-40 border-t px-4 py-3 shadow-[0_-8px_24px_rgb(0_0_0/0.25)] sm:px-6"
    >
      <div className="mx-auto flex max-w-[1320px] flex-wrap items-center gap-x-4 gap-y-2">
        <p className="text-fg min-w-0 flex-1 text-sm font-medium">
          {deal.kind === "market" ? t("market", { name: deal.title }) : t("sale")}
        </p>
        <Stars value={null} onChange={onRate} />
        <button type="button" onClick={onLater} className="text-fg-muted hover:text-fg text-sm">
          {t("later")}
        </button>
        <button
          type="button"
          onClick={onDismiss}
          aria-label={t("dismiss")}
          className="text-fg-dim hover:text-fg hover:bg-surface-2 grid size-8 place-items-center rounded-md"
        >
          <X className="size-4" aria-hidden />
        </button>
      </div>
    </aside>
  );
}
