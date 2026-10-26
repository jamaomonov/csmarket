// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ArticlePage, { generateMetadata } from "./page";

import type { Article, ArticlesPage } from "@/lib/articles";

const { notFound, permanentRedirect } = vi.hoisted(() => ({
  notFound: vi.fn(() => {
    throw new Error("NEXT_NOT_FOUND");
  }),
  permanentRedirect: vi.fn(() => {
    throw new Error("NEXT_REDIRECT");
  }),
}));
vi.mock("next/navigation", () => ({ notFound }));
vi.mock("@/i18n/navigation", () => ({
  permanentRedirect,
  Link: ({ href, children }: { href: string; children: React.ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));
vi.mock("next-intl", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  useTranslations: () => (k: string) => k,
}));
vi.mock("next-intl/server", () => ({
  getTranslations: () =>
    Promise.resolve(Object.assign((k: string) => k, { rich: (k: string) => k })),
  setRequestLocale: () => undefined,
}));
vi.mock("@/components/articles/ArticleStats", () => ({ ArticleStats: () => <div>stats</div> }));
vi.mock("@/components/articles/ViewBeacon", () => ({ ViewBeacon: () => null }));
vi.mock("@/components/skins/SkinCard", () => ({
  SkinCard: ({ item }: { item: { slug: string } }) => <div data-testid="skin">{item.slug}</div>,
}));
vi.mock("next/image", () => ({
  default: ({ alt }: { alt: string }) => <span role="img" aria-label={alt} />,
}));

const { fetchArticle, fetchArticles, fetchArticleLocales } = vi.hoisted(() => ({
  fetchArticle: vi.fn(),
  fetchArticles: vi.fn(),
  fetchArticleLocales: vi.fn(),
}));
vi.mock("@/lib/articles-server", () => ({ fetchArticle, fetchArticles, fetchArticleLocales }));

const COVER = {
  hash: "h",
  url: "/media/h.png",
  width: 640,
  height: 360,
  content_type: "image/png",
};
const ARTICLE: Article = {
  kind: "article",
  slug: "top-knives",
  section: "tops",
  title: "Топ ножей",
  description: "Описание",
  cover: COVER,
  cover_alt: "Обложка",
  published_at: "2026-10-20T10:00:00Z",
  updated_at: "2026-10-21T10:00:00Z",
  views: 3,
  likes: 1,
  body: "## Бабочка\n\n[[skin:butterfly]]\n\n[[skin:gone]]",
  locales: ["ru", "en"],
  embeds: {
    butterfly: { slug: "butterfly" } as Article["embeds"][string], // only the slug is read by the mock
  },
  related: [],
};
const EMPTY: ArticlesPage = { items: [], next_cursor: null };

const params = (slug: string, locale = "ru") => Promise.resolve({ locale, slug });
const searchParams = Promise.resolve({});

describe("an article", () => {
  beforeEach(() => {
    notFound.mockClear();
    permanentRedirect.mockClear();
    fetchArticleLocales.mockResolvedValue({ ru: ["tops"], uz: [], en: ["tops"] });
  });

  it("renders the article with its skin cards", async () => {
    fetchArticle.mockResolvedValue(ARTICLE);
    render(await ArticlePage({ params: params("top-knives"), searchParams }));
    expect(screen.getByRole("heading", { level: 1, name: "Топ ножей" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "Бабочка" })).toBeInTheDocument();
    expect(screen.getAllByTestId("skin").map((s) => s.textContent)).toEqual(["butterfly"]);
  });

  it("answers 404 for a missing translation", async () => {
    fetchArticle.mockResolvedValue(null);
    await expect(
      generateMetadata({ params: params("top-knives", "uz"), searchParams }),
    ).rejects.toThrow("NEXT_NOT_FOUND");
    await expect(ArticlePage({ params: params("top-knives", "uz"), searchParams })).rejects.toThrow(
      "NEXT_NOT_FOUND",
    );
  });

  it("redirects a former slug permanently", async () => {
    fetchArticle.mockResolvedValue({ kind: "redirect", slug: "new-name" });
    await expect(ArticlePage({ params: params("old-name", "en"), searchParams })).rejects.toThrow(
      "NEXT_REDIRECT",
    );
    expect(permanentRedirect).toHaveBeenCalledWith({ href: "/articles/new-name", locale: "en" });
  });

  it("lists only live locales in hreflang", async () => {
    fetchArticle.mockResolvedValue(ARTICLE);
    const meta = await generateMetadata({ params: params("top-knives"), searchParams });
    expect(Object.keys(meta.alternates?.languages ?? {})).toEqual(["ru", "en", "x-default"]);
    expect(meta.title).toBe("Топ ножей");
  });
});

describe("a section list", () => {
  beforeEach(() => {
    fetchArticles.mockResolvedValue(EMPTY);
  });

  it("is noindex while the section is empty in that language", async () => {
    fetchArticleLocales.mockResolvedValue({ ru: ["tops"], uz: [], en: [] });
    const meta = await generateMetadata({ params: params("news"), searchParams });
    expect(meta.robots).toEqual({ index: false, follow: true });
  });

  it("is indexed when it has articles, but not its cursor pages", async () => {
    fetchArticleLocales.mockResolvedValue({ ru: ["tops"], uz: [], en: [] });
    const meta = await generateMetadata({ params: params("tops"), searchParams });
    expect(meta.robots).not.toEqual({ index: false, follow: true });
    const more = await generateMetadata({
      params: params("tops"),
      searchParams: Promise.resolve({ cursor: "abc" }),
    });
    expect(more.robots).toEqual({ index: false, follow: true });
  });
});
