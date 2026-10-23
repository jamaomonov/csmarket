import { useTranslations } from "next-intl";

import { Stars } from "./Stars";

import type { PublicReview } from "@/lib/reviews";

interface ReviewListProps {
  items: PublicReview[];
  locale: string;
}

/** Published reviews; the text is rendered as text (React escapes it), never as markup. */
export function ReviewList({ items, locale }: ReviewListProps) {
  const t = useTranslations("web.reviews.page");
  const date = new Intl.DateTimeFormat(locale, { day: "numeric", month: "long", year: "numeric" });
  return (
    <ul className="flex flex-col gap-3">
      {items.map((r) => (
        <li
          key={r.id}
          className="border-border bg-surface flex flex-col gap-2 rounded-xl border p-4"
        >
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            {r.author_avatar_url !== null ? (
              // eslint-disable-next-line @next/next/no-img-element -- Steam CDN avatar, 32px; next/image adds nothing here
              <img src={r.author_avatar_url} alt="" className="size-8 rounded-full" />
            ) : null}
            <span className="min-w-0 max-w-full truncate font-medium">
              {r.author_name ?? t("anonymous")}
            </span>
            <Stars value={r.rating} size="sm" />
            <time dateTime={r.created_at} className="text-fg-dim ml-auto text-sm">
              {date.format(new Date(r.created_at))}
            </time>
          </div>
          <p className="text-fg-muted text-sm">{r.kind === "market" ? r.skin_name : t("sale")}</p>
          {r.text !== null ? <p className="whitespace-pre-line">{r.text}</p> : null}
        </li>
      ))}
    </ul>
  );
}
