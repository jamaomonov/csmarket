"use client";

import { Button } from "@csmarket/ui";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { ReviewList } from "./ReviewList";

import { getPublicReviews, type PublicReview, type ReviewLocale } from "@/lib/reviews";

interface ReviewsMoreProps {
  locale: ReviewLocale;
  /** The server-rendered first page's `next_cursor`. */
  cursor: string;
}

/** «Показать ещё»: further pages of the public list, fetched in the browser. */
export function ReviewsMore({ locale, cursor }: ReviewsMoreProps) {
  const t = useTranslations("web.reviews.page");
  const [items, setItems] = useState<PublicReview[]>([]);
  const [next, setNext] = useState<string | null>(cursor);
  const [state, setState] = useState<"idle" | "loading" | "failed">("idle");
  if (next === null && items.length === 0) return null;
  return (
    <div className="mt-3 flex flex-col gap-3">
      {items.length > 0 ? <ReviewList items={items} locale={locale} /> : null}
      {state === "failed" ? (
        <p role="alert" className="text-danger text-sm">
          {t("loadFailed")}
        </p>
      ) : null}
      {next !== null ? (
        <Button
          variant="secondary"
          disabled={state === "loading"}
          onClick={() => {
            setState("loading");
            getPublicReviews(locale, next).then(
              (page) => {
                setItems((had) => [...had, ...page.items]);
                setNext(page.next_cursor);
                setState("idle");
              },
              () => {
                setState("failed");
              },
            );
          }}
        >
          {t("more")}
        </Button>
      ) : null}
    </div>
  );
}
