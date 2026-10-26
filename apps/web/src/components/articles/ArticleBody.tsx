import { Markdown } from "@csmarket/ui";
import Image from "next/image";

import type { Article } from "@/lib/articles";

import { SkinCard } from "@/components/skins/SkinCard";
import { API_BASE } from "@/lib/api";
import { mediaPath } from "@/lib/articles";

interface ArticleBodyProps {
  article: Article;
  locale: string;
}

/** The article's Markdown with its skin cards (resolved by the API) and our own images. */
export function ArticleBody({ article, locale }: ArticleBodyProps) {
  return (
    <Markdown
      source={article.body}
      className="article-body"
      mediaUrl={(path) => API_BASE + mediaPath(path)}
      renderSkin={(slug) => {
        const item = article.embeds[slug];
        return item ? (
          <div className="my-4 max-w-[280px]">
            <SkinCard item={item} locale={locale} />
          </div>
        ) : null;
      }}
      renderImage={({ src, alt, width, height }) =>
        width !== undefined && height !== undefined ? (
          <Image
            src={src}
            alt={alt}
            width={width}
            height={height}
            sizes="(max-width: 768px) 100vw, 720px"
            className="my-4 h-auto w-full rounded-lg"
          />
        ) : (
          // eslint-disable-next-line @next/next/no-img-element -- a path typed by hand has no size for next/image
          <img src={src} alt={alt} loading="lazy" className="my-4 h-auto w-full rounded-lg" />
        )
      }
    />
  );
}
