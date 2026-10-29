import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { type AdminArticle } from "./api";
import { ArticleEditor } from "./ArticleEditor";

import { ApiError } from "@/lib/api";

const api = vi.hoisted(() => ({
  getArticle: vi.fn(),
  createArticle: vi.fn(),
  updateArticle: vi.fn(),
  publishArticle: vi.fn(),
  unpublishArticle: vi.fn(),
  uploadMedia: vi.fn(),
}));
vi.mock("./api", async (importOriginal) => ({ ...(await importOriginal<object>()), ...api }));
const catalogue = vi.hoisted(() => ({ findItems: vi.fn() }));
vi.mock("@/features/catalogue/api", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  ...catalogue,
}));

const COVER = {
  hash: "c",
  url: "/media/c.png",
  width: 1280,
  height: 720,
  content_type: "image/png",
};
const TR = {
  title: "Топ ножей",
  description: "Описание",
  cover_alt: "Нож",
  body: "Текст.",
  ready: true,
  updated_at: "2026-10-20T10:00:00Z",
};
const ARTICLE: AdminArticle = {
  id: "a1",
  section: "tops",
  slug: "top-knives",
  status: "draft",
  cover: COVER,
  translations: { ru: TR, uz: null, en: null },
  live_locales: [],
  views: 0,
  likes: 0,
  published_at: null,
  updated_at: "2026-10-20T10:00:00Z",
  created_at: "2026-10-20T10:00:00Z",
};

function renderAt(path: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/articles/new" element={<ArticleEditor />} />
          <Route path="/articles/:id" element={<ArticleEditor />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const body = () => screen.getByLabelText<HTMLTextAreaElement>("Текст");

describe("ArticleEditor", () => {
  beforeEach(() => {
    localStorage.clear();
    for (const f of Object.values(api)) f.mockReset();
    api.getArticle.mockResolvedValue(ARTICLE);
  });

  it("creates an article and lands on its editor", async () => {
    api.createArticle.mockResolvedValue(ARTICLE);
    renderAt("/articles/new");
    fireEvent.change(screen.getByLabelText("Адрес (slug)"), { target: { value: "top-knives" } });
    fireEvent.change(screen.getByLabelText("Заголовок"), { target: { value: "Топ ножей" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    await waitFor(() => {
      expect(api.createArticle).toHaveBeenCalled();
    });
    const [sent] = api.createArticle.mock.calls[0] as [Record<string, unknown>];
    expect(sent).toMatchObject({ section: "news", slug: "top-knives" });
    expect(sent.translations).toMatchObject({ ru: { title: "Топ ножей" } });
    expect(await screen.findByDisplayValue("Описание")).toBeInTheDocument();
  });

  it("saves translations per tab", async () => {
    api.updateArticle.mockResolvedValue(ARTICLE);
    renderAt("/articles/a1");
    await screen.findByDisplayValue("Топ ножей");
    fireEvent.click(screen.getByRole("tab", { name: /EN/ }));
    fireEvent.change(screen.getByLabelText("Заголовок"), { target: { value: "Top knives" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    await waitFor(() => {
      expect(api.updateArticle).toHaveBeenCalled();
    });
    const [, sent] = api.updateArticle.mock.calls[0] as [
      string,
      Record<string, Record<string, unknown>>,
    ];
    expect(sent.translations?.en).toMatchObject({ title: "Top knives" });
    expect(sent.translations?.ru).toMatchObject({ title: "Топ ножей" });
    expect(sent.translations?.uz).toBeUndefined();
  });

  it("inserts an uploaded image with its size at the caret", async () => {
    api.uploadMedia.mockResolvedValue({
      ...COVER,
      hash: "p",
      url: "/media/p.png",
      width: 640,
      height: 360,
    });
    renderAt("/articles/a1");
    await screen.findByDisplayValue("Топ ножей");
    body().setSelectionRange(0, 0);
    const file = new File([new Uint8Array(8)], "shot.png", { type: "image/png" });
    fireEvent.change(screen.getByLabelText("Картинка в текст"), { target: { files: [file] } });
    await waitFor(() => {
      expect(body().value).toBe("![](/media/p.png?w=640&h=360)Текст.");
    });
  });

  it("inserts a skin embed on its own line", async () => {
    catalogue.findItems.mockResolvedValue({
      items: [{ slug: "ak-47-redline-field-tested", name: "AK-47 | Redline (Field-Tested)" }],
    });
    renderAt("/articles/a1");
    await screen.findByDisplayValue("Топ ножей");
    body().setSelectionRange(6, 6);
    fireEvent.click(screen.getByRole("button", { name: "Скин" }));
    fireEvent.change(screen.getByLabelText("Поиск скина"), { target: { value: "redline" } });
    fireEvent.mouseDown(await screen.findByRole("option", { name: /AK-47 \| Redline/ }));
    expect(body().value).toBe("Текст.\n\n[[skin:ak-47-redline-field-tested]]\n\n");
  });

  it("shows why the API refused to publish", async () => {
    api.publishArticle.mockRejectedValue(
      new ApiError(409, "Conflict", { code: "publish_needs_translation", detail: "x" }),
    );
    renderAt("/articles/a1");
    await screen.findByDisplayValue("Топ ножей");
    fireEvent.click(screen.getByRole("button", { name: "Опубликовать" }));
    fireEvent.click(screen.getByRole("button", { name: "Да, опубликовать" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Чтобы опубликовать, отметьте готовым хотя бы один перевод.",
    );
  });

  it("warns about the redirect when renaming a published article", async () => {
    api.getArticle.mockResolvedValue({
      ...ARTICLE,
      status: "published",
      published_at: "2026-10-20T10:00:00Z",
    });
    renderAt("/articles/a1");
    const slug = await screen.findByDisplayValue("top-knives");
    expect(screen.queryByText(/будет перенаправлять/)).toBeNull();
    fireEvent.change(slug, { target: { value: "best-knives" } });
    expect(screen.getByText(/Старый адрес будет перенаправлять на новый/)).toBeInTheDocument();
  });

  it("offers back an unsaved local draft", async () => {
    localStorage.setItem(
      "admin.article-draft.a1",
      JSON.stringify({
        section: "tops",
        slug: "top-knives",
        cover: COVER,
        translations: { ru: { ...TR, title: "Черновик заголовка" } },
      }),
    );
    renderAt("/articles/a1");
    fireEvent.click(await screen.findByRole("button", { name: "Восстановить" }));
    expect(screen.getByDisplayValue("Черновик заголовка")).toBeInTheDocument();
  });

  it("sends a cleared translation so it leaves the site", async () => {
    api.getArticle.mockResolvedValue({
      ...ARTICLE,
      translations: { ru: TR, uz: { ...TR, title: "Pichoqlar" }, en: null },
    });
    api.updateArticle.mockResolvedValue(ARTICLE);
    renderAt("/articles/a1");
    await screen.findByDisplayValue("Топ ножей");
    fireEvent.click(screen.getByRole("tab", { name: /UZ/ }));
    fireEvent.change(screen.getByLabelText("Заголовок"), { target: { value: "" } });
    fireEvent.change(screen.getByLabelText("Описание"), { target: { value: "" } });
    fireEvent.change(screen.getByLabelText("Подпись к обложке"), { target: { value: "" } });
    fireEvent.change(body(), { target: { value: "" } });
    fireEvent.click(screen.getByRole("checkbox", { name: "Перевод готов" }));
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    await waitFor(() => {
      expect(api.updateArticle).toHaveBeenCalled();
    });
    const [, sent] = api.updateArticle.mock.calls[0] as [
      string,
      { translations?: { uz?: unknown } },
    ];
    expect(sent.translations?.uz).toMatchObject({ title: "", body: "", ready: false });
  });
});
