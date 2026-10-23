import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { type AdminReview } from "./api";
import { ReviewsPage } from "./ReviewsPage";

const api = vi.hoisted(() => ({
  getReviews: vi.fn(),
  resolveReview: vi.fn(),
  setReviewHidden: vi.fn(),
  getReviewSettings: vi.fn(),
  saveReviewSettings: vi.fn(),
}));
vi.mock("./api", async (importOriginal) => ({ ...(await importOriginal<object>()), ...api }));

const BAD: AdminReview = {
  id: "r1",
  kind: "market",
  number: "AB12CD34",
  rating: 2,
  text: "Долго ждал обмен",
  locale: "ru",
  hidden: false,
  published: false,
  user: { id: "u1", display_name: "Aziz", avatar_url: null, email_confirmed: false },
  created_at: "2026-10-23T10:00:00Z",
  updated_at: "2026-10-23T10:00:00Z",
  resolved_at: null,
  resolved_by: null,
  resolved_note: null,
};

function renderPage(path = "/reviews") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <ReviewsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ReviewsPage", () => {
  beforeEach(() => {
    Object.values(api).forEach((f) => f.mockReset());
    api.getReviews.mockResolvedValue({ items: [BAD], next_cursor: null, bad_open: 2 });
    api.getReviewSettings.mockResolvedValue({
      reviews_public: false,
      published_count: 12,
      updated_at: null,
      updated_by: null,
    });
  });

  it("opens on «Плохие» with the count, and lists a review with its links", async () => {
    renderPage();
    const row = await screen.findByTestId("review-r1");
    expect(api.getReviews).toHaveBeenCalledWith({ tab: "bad", kind: "", locale: "" }, null);
    expect(screen.getByRole("tab", { name: /Плохие/ })).toHaveTextContent("2");
    expect(within(row).getByRole("img", { name: "2 из 5" })).toBeInTheDocument();
    expect(within(row).getByText("Долго ждал обмен")).toBeInTheDocument();
    expect(within(row).getByText(/Маркет · Русский/)).toBeInTheDocument();
    expect(within(row).getByRole("link", { name: "AB12CD34" })).toHaveAttribute(
      "href",
      "/orders/AB12CD34",
    );
    expect(within(row).getByRole("link", { name: /Aziz/ })).toHaveAttribute("href", "/users/u1");
    expect(within(row).getByText("без email")).toBeInTheDocument();
    // a bad review is never on the site: nothing to hide
    expect(within(row).queryByRole("button", { name: "Скрыть с сайта" })).toBeNull();
  });

  it("marks a user with a confirmed email to answer at", async () => {
    api.getReviews.mockResolvedValue({
      items: [{ ...BAD, user: { ...BAD.user, email_confirmed: true } }],
      next_cursor: null,
      bad_open: 1,
    });
    renderPage();
    const row = await screen.findByTestId("review-r1");
    expect(within(row).getByText("есть email")).toBeInTheDocument();
  });

  it("says the bad tab is all done when empty", async () => {
    api.getReviews.mockResolvedValue({ items: [], next_cursor: null, bad_open: 0 });
    renderPage();
    expect(await screen.findByText("Плохих отзывов нет — всё разобрано.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: /Хорошие/ }));
    expect(await screen.findByText("Отзывов нет.")).toBeInTheDocument();
  });

  it("switches tabs and filters", async () => {
    renderPage();
    await screen.findByTestId("review-r1");
    fireEvent.click(screen.getByRole("tab", { name: /Хорошие/ }));
    await waitFor(() => {
      expect(api.getReviews).toHaveBeenCalledWith({ tab: "good", kind: "", locale: "" }, null);
    });
    fireEvent.change(screen.getByRole("combobox", { name: "Тип" }), { target: { value: "sale" } });
    await waitFor(() => {
      expect(api.getReviews).toHaveBeenCalledWith({ tab: "good", kind: "sale", locale: "" }, null);
    });
    fireEvent.change(screen.getByRole("combobox", { name: "Язык" }), { target: { value: "uz" } });
    await waitFor(() => {
      expect(api.getReviews).toHaveBeenCalledWith(
        { tab: "good", kind: "sale", locale: "uz" },
        null,
      );
    });
  });

  it("«Разобрано» asks what was done and sends the note", async () => {
    api.resolveReview.mockResolvedValue({
      ...BAD,
      resolved_at: "2026-10-23T11:00:00Z",
      resolved_by: { id: "a1", display_name: "Owner", avatar_url: null, email_confirmed: true },
      resolved_note: "Позвонили",
    });
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Разобрано" }));
    const done = screen.getByRole("button", { name: "Отметить" });
    expect(done).toBeDisabled();
    fireEvent.change(screen.getByRole("textbox", { name: "Что сделали" }), {
      target: { value: " Позвонили " },
    });
    fireEvent.click(done);
    await waitFor(() => {
      expect(api.resolveReview).toHaveBeenCalledWith(
        "r1",
        "Позвонили",
        expect.stringMatching(/^admin-review-resolve-/),
      );
    });
  });

  it("hides a good review from the site; a hidden one offers «Показать»", async () => {
    const GOOD = { ...BAD, rating: 5, published: true };
    api.getReviews.mockResolvedValue({ items: [GOOD], next_cursor: null, bad_open: 0 });
    api.setReviewHidden.mockResolvedValue({ ...GOOD, hidden: true });
    renderPage();
    const hide = await screen.findByRole("button", { name: "Скрыть с сайта" });
    api.getReviews.mockResolvedValue({
      items: [{ ...GOOD, hidden: true, published: false }],
      next_cursor: null,
      bad_open: 0,
    });
    fireEvent.click(hide);
    await waitFor(() => {
      expect(api.setReviewHidden).toHaveBeenCalledWith(
        "r1",
        true,
        expect.stringMatching(/^admin-review-hide-/),
      );
    });
    expect(await screen.findByRole("button", { name: "Показать" })).toBeInTheDocument();
  });

  it("shows a resolved review's note, who and no «Разобрано»", async () => {
    api.getReviews.mockResolvedValue({
      items: [
        {
          ...BAD,
          resolved_at: "2026-10-23T11:00:00Z",
          resolved_by: { id: "a1", display_name: "Owner", avatar_url: null, email_confirmed: true },
          resolved_note: "Позвонили",
        },
      ],
      next_cursor: null,
      bad_open: 1,
    });
    renderPage();
    const row = await screen.findByTestId("review-r1");
    expect(within(row).getByText(/Owner · Позвонили/)).toBeInTheDocument();
    expect(within(row).queryByRole("button", { name: "Разобрано" })).toBeNull();
  });

  it("a resolved line without a note ends on who resolved it", async () => {
    api.getReviews.mockResolvedValue({
      items: [
        {
          ...BAD,
          resolved_at: "2026-10-23T11:00:00Z",
          resolved_by: { id: "a1", display_name: "Owner", avatar_url: null, email_confirmed: true },
          resolved_note: null,
        },
      ],
      next_cursor: null,
      bad_open: 0,
    });
    renderPage();
    const row = await screen.findByTestId("review-r1");
    expect(
      within(row)
        .getByText(/Разобрано/)
        .textContent.trimEnd(),
    ).toMatch(/Owner$/);
  });
});
