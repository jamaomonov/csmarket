"use client";

import { Button } from "@csmarket/ui";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { ReviewDialog } from "./ReviewDialog";
import { Stars } from "./Stars";

import { dealReviewKey, getDealReview, type ReviewKind } from "@/lib/reviews";

interface ReviewSlotProps {
  kind: ReviewKind;
  number: string;
  /** The skin's name, for the modal. */
  title: string;
  imageUrl: string | null;
}

/** On a succeeded deal's page: «Оставить отзыв», or the stars given (editable for 14 days). */
export function ReviewSlot({ kind, number, title, imageUrl }: ReviewSlotProps) {
  const t = useTranslations("web.reviews.account");
  const [open, setOpen] = useState(false);
  const q = useQuery({
    queryKey: dealReviewKey(kind, number),
    queryFn: () => getDealReview(kind, number),
    retry: false,
  });
  const data = q.data;
  if (data === undefined || (data.review === null && !data.can_review)) return null;
  const review = data.review;
  return (
    <section
      aria-label={t("label")}
      className="border-border flex flex-wrap items-center gap-3 rounded-xl border p-4"
    >
      {review === null ? (
        <Button
          onClick={() => {
            setOpen(true);
          }}
        >
          {t("leave")}
        </Button>
      ) : (
        <>
          <span className="text-fg-muted text-sm">{t("yours")}</span>
          <Stars value={review.rating} size="sm" />
          {data.can_review ? (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setOpen(true);
              }}
            >
              {t("edit")}
            </Button>
          ) : null}
        </>
      )}
      {open ? (
        <ReviewDialog
          deal={{ kind, number, title, image_url: imageUrl }}
          initialRating={review?.rating ?? null}
          initialText={review?.text ?? null}
          onClose={() => {
            setOpen(false);
          }}
        />
      ) : null}
    </section>
  );
}
