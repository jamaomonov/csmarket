import { Eye, Heart } from "lucide-react";
import Image from "next/image";

import type { ArticleCard as Card } from "@/lib/articles";

import { Link } from "@/i18n/navigation";
import { API_BASE } from "@/lib/api";
import { mediaPath } from "@/lib/articles";
import { articlePath } from "@/lib/paths";

interface ArticleCardProps {
  article: Card;
  locale: string;
  /** Load the cover eagerly: the first row, likely the page's LCP. */
  priority?: boolean;
}

/** One article in a list: the cover, the title, the teaser, the date and the counters. */
export function ArticleCard({ article, locale, priority = false }: ArticleCardProps) {
  const date = new Intl.DateTimeFormat(locale, { day: "numeric", month: "long", year: "numeric" });
  return (
    <Link
      href={articlePath(article.slug)}
      className="border-border bg-surface hover:border-accent group flex flex-col overflow-hidden rounded-xl border transition-colors"
    >
      <div className="bg-surface-2 relative aspect-[16/9]">
        <Image
          src={API_BASE + mediaPath(article.cover.url)}
          alt={article.cover_alt}
          fill
          sizes="(max-width: 640px) 100vw, (max-width: 1024px) 50vw, 320px"
          className="object-cover"
          priority={priority}
        />
      </div>
      <div className="flex flex-1 flex-col gap-2 p-4">
        <h2 className="text-lg font-semibold leading-snug group-hover:underline">
          {article.title}
        </h2>
        <p className="text-fg-muted line-clamp-3 text-sm">{article.description}</p>
        <div className="text-fg-dim mt-auto flex items-center gap-3 pt-2 text-xs">
          <time dateTime={article.published_at}>{date.format(new Date(article.published_at))}</time>
          <span className="ml-auto flex items-center gap-1">
            <Eye className="size-3.5" aria-hidden />
            {article.views}
          </span>
          <span className="flex items-center gap-1">
            <Heart className="size-3.5" aria-hidden />
            {article.likes}
          </span>
        </div>
      </div>
    </Link>
  );
}
