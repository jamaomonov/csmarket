"use client";

import { Eye, Heart } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import type { ArticleMe } from "@/lib/articles";

import { session } from "@/lib/api";

interface ArticleStatsProps {
  slug: string;
  /** The cached page's numbers, shown until mine arrive. */
  likes: number;
  views: number;
}

interface LikeState {
  likes: number;
  liked: boolean;
}

/** Views and the like button. My own numbers load here so the article page stays cached for
 * everyone; anyone may like, signed in or not. */
export function ArticleStats({ slug, likes, views }: ArticleStatsProps) {
  const t = useTranslations("web.articles");
  const path = `/api/v1/articles/${encodeURIComponent(slug)}`;
  const [seen, setSeen] = useState(views);
  const [like, setLike] = useState<LikeState>({ likes, liked: false });
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    session
      .api<ArticleMe>(`${path}/me`)
      .then((me) => {
        setSeen(me.views);
        setLike({ likes: me.likes, liked: me.liked });
      })
      .catch(() => undefined);
  }, [path]);

  const toggle = () => {
    const before = like;
    const on = !before.liked;
    setBusy(true);
    setLike({ likes: before.likes + (on ? 1 : -1), liked: on });
    session
      .api<LikeState>(`${path}/like`, { method: on ? "PUT" : "DELETE" })
      .then(setLike)
      .catch(() => {
        setLike(before);
      })
      .finally(() => {
        setBusy(false);
      });
  };

  return (
    <div className="text-fg-muted flex items-center gap-4 text-sm">
      <span className="flex items-center gap-1.5">
        <Eye className="size-4" aria-hidden />
        {t("views", { n: seen })}
      </span>
      <button
        type="button"
        onClick={toggle}
        disabled={busy}
        aria-pressed={like.liked}
        aria-label={like.liked ? t("unlike") : t("like")}
        className="border-border hover:border-accent aria-pressed:text-danger flex min-h-10 items-center gap-1.5 rounded-full border px-3"
      >
        <Heart className="size-4 [[aria-pressed=true]_&]:fill-current" aria-hidden />
        <span>{like.likes}</span>
      </button>
    </div>
  );
}
