/** Operator words for «Статьи». */
import type { ArticleLocale, ArticleStatus, Section } from "./api";

import { errorText } from "@/features/users/labels";
import { ApiError } from "@/lib/api";

export const SECTIONS: readonly Section[] = ["news", "guides", "tops"];
export const STATUSES: readonly ArticleStatus[] = ["draft", "published"];
export const LOCALES: readonly ArticleLocale[] = ["ru", "uz", "en"];

export const SECTION_LABEL: Record<Section, string> = {
  news: "Новости",
  guides: "Гайды",
  tops: "Подборки",
};
export const STATUS_LABEL: Record<ArticleStatus, string> = {
  draft: "Черновик",
  published: "Опубликована",
};
export const LOCALE_LABEL: Record<ArticleLocale, string> = { ru: "RU", uz: "UZ", en: "EN" };

export const ARTICLE_ERRORS: Record<string, string> = {
  slug_invalid: "Адрес: 3–80 латинских строчных букв, цифр и дефисов; не news, guides, tops.",
  slug_taken: "Этот адрес уже занят другой статьёй.",
  cover_not_found: "Сначала загрузите обложку.",
  publish_needs_cover: "Чтобы опубликовать, добавьте обложку.",
  publish_needs_translation: "Чтобы опубликовать, отметьте готовым хотя бы один перевод.",
  article_not_found: "Статья не найдена.",
  media_empty: "Файл пустой.",
  media_too_large: "Файл больше 5 МБ.",
  media_type: "Подходят только JPG, PNG или WebP.",
};

export function articleErrorText(err: unknown): string {
  const code = err instanceof ApiError ? err.code : undefined;
  return (code !== undefined ? ARTICLE_ERRORS[code] : undefined) ?? errorText(err);
}
