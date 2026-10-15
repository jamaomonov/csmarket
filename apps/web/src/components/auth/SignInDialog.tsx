"use client";

import { buttonVariants, cn, LogoMark } from "@csmarket/ui";
import { X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useId, useRef } from "react";

import { SteamIcon } from "@/components/icons/SteamIcon";
import { useAuth } from "@/lib/auth";

interface SignInDialogProps {
  open: boolean;
  onClose: () => void;
  locale: string;
}

/**
 * «Войдите, чтобы купить»: a visitor who pressed buy gets the Steam sign-in in a modal
 * instead of a sign-in button in place of the form. A native `<dialog>` opened with
 * `showModal()`: the browser keeps focus inside, Escape closes it, the page behind is inert.
 * A click on the backdrop (the dialog element itself) closes it too.
 */
export function SignInDialog({ open, onClose, locale }: SignInDialogProps) {
  const t = useTranslations("web.buy.signInDialog");
  const { signInHref } = useAuth();
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      onClose={onClose}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      className="bg-surface-solid border-border text-fg backdrop:bg-bg/70 m-auto w-[min(440px,calc(100vw-32px))] rounded-2xl border p-0 shadow-[0_24px_60px_rgb(0_0_0/0.5)] backdrop:backdrop-blur-sm"
    >
      <div className="relative flex flex-col items-center gap-4 px-6 pb-7 pt-9 text-center sm:px-8">
        <button
          type="button"
          onClick={onClose}
          aria-label={t("close")}
          className="text-fg-dim hover:text-fg hover:bg-surface-2 focus-visible:ring-accent absolute right-3 top-3 grid size-9 place-items-center rounded-lg transition-colors focus-visible:outline-none focus-visible:ring-2"
        >
          <X className="size-5" aria-hidden />
        </button>
        <LogoMark className="text-accent size-12" />
        <h2 id={titleId} className="text-h3 font-semibold tracking-tight">
          {t("title")}
        </h2>
        <p className="text-fg-muted text-body max-w-xs">{t("text")}</p>
        <a
          href={signInHref(locale)}
          className={cn(buttonVariants({ size: "lg" }), "mt-2 w-full gap-2")}
        >
          <SteamIcon className="size-5" aria-hidden />
          {t("cta")}
        </a>
      </div>
    </dialog>
  );
}
