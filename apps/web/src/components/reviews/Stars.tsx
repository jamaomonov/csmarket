"use client";

import { cn } from "@csmarket/ui";
import { Star } from "lucide-react";
import { useTranslations } from "next-intl";
import { useId, useState } from "react";

interface StarsProps {
  value: number | null;
  /** Given: the stars are a radio group the user picks from; absent: a read-only picture. */
  onChange?: (rating: number) => void;
  size?: "sm" | "md" | "lg";
}

const SIZES = { sm: "size-4", md: "size-6", lg: "size-8" } as const;
const RATINGS = [1, 2, 3, 4, 5] as const;

/**
 * 1–5 stars: picked (`onChange`) or shown («Оценка 4 из 5»). Picked, they are native radio inputs
 * under one name: one Tab stop, arrow keys move the choice, a reader says «2 из 5»; each star is
 * a 40 px target and lights up to the hovered one.
 */
export function Stars({ value, onChange, size = "md" }: StarsProps) {
  const t = useTranslations("web.reviews.stars");
  const name = useId();
  const [hover, setHover] = useState<number | null>(null);
  const lit = hover ?? value;
  const icon = (n: number) => (
    <Star
      aria-hidden
      className={cn(
        SIZES[size],
        lit !== null && n <= lit ? "fill-warning text-warning" : "text-fg-dim",
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
    <div
      role="radiogroup"
      aria-label={t("label")}
      className="inline-flex gap-1.5"
      onMouseLeave={() => {
        setHover(null);
      }}
    >
      {RATINGS.map((n) => (
        <label
          key={n}
          onMouseEnter={() => {
            setHover(n);
          }}
          className={cn(
            "has-[:focus-visible]:ring-accent cursor-pointer rounded-md has-[:focus-visible]:ring-2",
            size === "lg" ? "p-1.5" : "p-2",
          )}
        >
          <input
            type="radio"
            name={name}
            value={n}
            checked={value === n}
            aria-label={t("star", { n })}
            onChange={() => {
              onChange(n);
            }}
            className="sr-only"
          />
          {icon(n)}
        </label>
      ))}
    </div>
  );
}
