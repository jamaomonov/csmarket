"use client";

import { isLocale } from "@csmarket/i18n";
import { Button } from "@csmarket/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { X } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useEffect, useId, useRef, useState } from "react";

import { Stars } from "./Stars";

import { useAuth } from "@/lib/auth";
import {
  dealReviewKey,
  isGood,
  mintReviewKey,
  REVIEW_PENDING_KEY,
  saveReview,
  TEXT_MAX,
  type ReviewKind,
} from "@/lib/reviews";

export interface ReviewDeal {
  kind: ReviewKind;
  number: string;
  title: string;
  image_url: string | null;
}

interface ReviewDialogProps {
  deal: ReviewDeal;
  /** A star already chosen (on the strip), or the rating being edited. */
  initialRating?: number | null;
  initialText?: string | null;
  onClose: () => void;
  /** «Не сейчас» (the live prompt and the strip); without it the button is not shown. */
  onLater?: () => void;
  /** Changing a review already sent: «Изменить отзыв» as the title. */
  editing?: boolean;
}

interface Sent {
  rating: number;
  text: string | null;
}

/**
 * The review modal, mounted only while open: a native `<dialog>` opened with `showModal()`
 * (focus kept inside, Escape closes it; the backdrop only while nothing was changed, so a stray
 * tap never loses typed text). Focus goes back to the opener on close. The text is sent as typed
 * and never rendered as markup. One `Idempotency-Key` per body, so a retry after a lost answer
 * replays.
 */
export function ReviewDialog({
  deal,
  initialRating = null,
  initialText = null,
  onClose,
  onLater,
  editing = false,
}: ReviewDialogProps) {
  const t = useTranslations("web.reviews.prompt");
  const locale = useLocale();
  const qc = useQueryClient();
  const { user } = useAuth();
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const key = useRef<{ body: string; key: string } | null>(null);
  const [rating, setRating] = useState<number | null>(initialRating);
  const [text, setText] = useState(initialText ?? "");

  useEffect(() => {
    const dialog = ref.current;
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    if (dialog !== null && !dialog.open) {
      // jsdom has no showModal; the attribute keeps the content reachable there.
      if (typeof dialog.showModal === "function") dialog.showModal();
      else dialog.setAttribute("open", "");
    }
    return () => {
      if (dialog?.open === true && typeof dialog.close === "function") dialog.close();
      if (opener?.isConnected === true) opener.focus();
    };
  }, []);

  const send = useMutation({
    mutationFn: (body: Sent) => {
      const json = JSON.stringify(body);
      if (key.current?.body !== json) key.current = { body: json, key: mintReviewKey() };
      const lang = isLocale(locale) ? locale : "ru";
      return saveReview(deal.kind, deal.number, { ...body, locale: lang }, key.current.key);
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: REVIEW_PENDING_KEY });
      void qc.invalidateQueries({ queryKey: dealReviewKey(deal.kind, deal.number) });
    },
  });

  const sent = send.isSuccess ? send.variables : null;
  const title = editing
    ? t("titleEdit")
    : deal.kind === "market"
      ? t("titleMarket")
      : t("titleSale");
  const placeholder =
    rating === null
      ? t("placeholderAny")
      : isGood(rating)
        ? t("placeholderGood")
        : t("placeholderBad");
  const untouched = rating === initialRating && text === (initialText ?? "");
  const canContact = user?.email != null && user.email_verified;

  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      onClose={onClose}
      onClick={(e) => {
        if (e.target === e.currentTarget && (untouched || sent !== null)) onClose();
      }}
      className="bg-surface-solid border-border text-fg backdrop:bg-bg/70 m-auto w-[min(480px,calc(100vw-32px))] rounded-2xl border p-0 shadow-[0_24px_60px_rgb(0_0_0/0.5)] backdrop:backdrop-blur-sm"
    >
      <div className="relative flex flex-col items-center gap-4 px-6 pb-7 pt-9 text-center sm:px-8">
        <button
          type="button"
          onClick={onClose}
          aria-label={t("close")}
          className="text-fg-dim hover:text-fg hover:bg-surface-2 focus-visible:ring-accent absolute right-3 top-3 grid size-9 place-items-center rounded-lg focus-visible:outline-none focus-visible:ring-2"
        >
          <X className="size-5" aria-hidden />
        </button>
        {deal.image_url !== null ? (
          // eslint-disable-next-line @next/next/no-img-element -- a Steam CDN image already cut to size
          <img src={deal.image_url} alt="" className="h-24 w-auto object-contain" />
        ) : null}
        {deal.title !== "" ? <p className="text-fg-muted -mt-2 text-sm">{deal.title}</p> : null}
        <h2 id={titleId} className="text-h3 font-semibold tracking-tight">
          {sent === null ? title : t("thanks")}
        </h2>
        {sent !== null ? (
          <div role="status" className="flex w-full flex-col items-center gap-4">
            {!isGood(sent.rating) ? (
              <p className="text-fg-muted">{canContact ? t("weWillContact") : t("weWillLook")}</p>
            ) : null}
            {/* the form it replaced held focus: «Готово» takes it, so it is not lost */}
            <Button autoFocus onClick={onClose} className="w-full sm:w-auto">
              {t("done")}
            </Button>
          </div>
        ) : (
          <form
            className="flex w-full flex-col items-center gap-4"
            onSubmit={(e) => {
              e.preventDefault();
              if (rating !== null) send.mutate({ rating, text: text.trim() || null });
            }}
          >
            <Stars value={rating} onChange={setRating} size="lg" />
            {rating === null ? (
              <p className="text-fg-dim -mt-2 text-sm">{t("pickRating")}</p>
            ) : null}
            <textarea
              aria-label={t("textLabel")}
              value={text}
              maxLength={TEXT_MAX}
              rows={4}
              placeholder={placeholder}
              onChange={(e) => {
                setText(e.target.value);
              }}
              className="border-border bg-bg w-full rounded-lg border p-3 text-base"
            />
            {send.isError ? (
              <p role="alert" className="text-danger text-sm">
                {t("failed")}
              </p>
            ) : null}
            <div className="flex w-full flex-col gap-2 sm:flex-row sm:justify-center">
              <Button type="submit" disabled={rating === null || send.isPending}>
                {send.isPending ? t("sending") : t("send")}
              </Button>
              {onLater !== undefined ? (
                <Button variant="ghost" onClick={onLater}>
                  {t("later")}
                </Button>
              ) : null}
            </div>
          </form>
        )}
      </div>
    </dialog>
  );
}
