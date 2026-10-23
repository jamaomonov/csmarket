"use client";

import { cn } from "@csmarket/ui";
import { Star } from "lucide-react";
import { useTranslations } from "next-intl";

interface StarsProps {
  value: number | null;
  /** Given: the stars are a radio group the user picks from; absent: a read-only picture. */
  onChange?: (rating: number) => void;
  size?: "sm" | "md" | "lg";
}

const SIZES = { sm: "size-4", md: "size-6", lg: "size-8" } as const;
const RATINGS = [1, 2, 3, 4, 5] as const;

/** 1–5 stars: picked (`onChange`) or shown («4 из 5»). */
export function Stars({ value, onChange, size = "md" }: StarsProps) {
  const t = useTranslations("web.reviews.stars");
  const icon = (n: number) => (
    <Star
      aria-hidden
      className={cn(
        SIZES[size],
        value !== null && n <= value ? "fill-warning text-warning" : "text-fg-dim",
      )}
    />
  );
  if (onChange === undefined) {
    return (
      <span role="img" aria-label={t("of", { n: value ?? 0 })} className="inline-flex gap-0.5">
        {RATINGS.map((n) => (
          <span key={n}>{icon(n)}</span>
        ))}
      </span>
    );
  }
  return (
    <div role="radiogroup" aria-label={t("label")} className="inline-flex gap-1">
      {RATINGS.map((n) => (
        <button
          key={n}
          type="button"
          role="radio"
          aria-checked={value === n}
          aria-label={t("star", { n })}
          onClick={() => {
            onChange(n);
          }}
          className="focus-visible:ring-accent rounded-md p-1 focus-visible:outline-none focus-visible:ring-2"
        >
          {icon(n)}
        </button>
      ))}
    </div>
  );
}
