import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { type AdminArticleRow } from "./api";
import { ArticlesPage } from "./ArticlesPage";

const api = vi.hoisted(() => ({ listArticles: vi.fn() }));
vi.mock("./api", async (importOriginal) => ({ ...(await importOriginal<object>()), ...api }));

const ROW: AdminArticleRow = {
  id: "a1",
  section: "tops",
  slug: "top-budget-knives",
  status: "published",
  title: "Топ бюджетных ножей",
  live_locales: ["ru", "en"],
  views: 120,
  likes: 7,
  published_at: "2026-10-20T10:00:00Z",
  updated_at: "2026-10-21T10:00:00Z",
};

function renderPage(path = "/articles") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/articles" element={<ArticlesPage />} />
          <Route path="/articles/new" element={<p>editor</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ArticlesPage", () => {
  beforeEach(() => {
    api.listArticles.mockReset().mockResolvedValue([ROW]);
  });

  it("lists articles with live locales and counters", async () => {
    renderPage();
    const link = await screen.findByRole("link", { name: "Топ бюджетных ножей" });
    expect(link).toHaveAttribute("href", "/articles/a1");
    const row = within(screen.getByRole("listitem"));
    expect(row.getByText("Подборки")).toBeInTheDocument();
    expect(row.getByText("Опубликована")).toBeInTheDocument();
    expect(row.getByText("RU")).toBeInTheDocument();
    expect(row.getByText("EN")).toBeInTheDocument();
    expect(row.queryByText("UZ")).toBeNull();
    expect(row.getByText("120")).toBeInTheDocument();
    expect(row.getByText("7")).toBeInTheDocument();
  });

  it("filters by section and status from the URL", async () => {
    renderPage("/articles?section=news&status=draft");
    await waitFor(() => {
      expect(api.listArticles).toHaveBeenCalledWith({ section: "news", status: "draft" });
    });
  });

  it("names an untitled draft", async () => {
    api.listArticles.mockResolvedValue([{ ...ROW, title: "", status: "draft", live_locales: [] }]);
    renderPage();
    expect(await screen.findByRole("link", { name: "Без названия" })).toBeInTheDocument();
  });

  it("«Новая статья» goes to the editor", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("link", { name: "Новая статья" }));
    expect(await screen.findByText("editor")).toBeInTheDocument();
  });
});
