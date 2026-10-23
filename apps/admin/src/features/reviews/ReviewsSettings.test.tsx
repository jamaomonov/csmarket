import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ReviewsSettings } from "./ReviewsSettings";

const api = vi.hoisted(() => ({ getReviewSettings: vi.fn(), saveReviewSettings: vi.fn() }));
vi.mock("./api", async (importOriginal) => ({ ...(await importOriginal<object>()), ...api }));

const OFF = { reviews_public: false, published_count: 12, updated_at: null, updated_by: null };

function renderBlock() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <ReviewsSettings />
    </QueryClientProvider>,
  );
}

describe("ReviewsSettings", () => {
  beforeEach(() => {
    Object.values(api).forEach((f) => f.mockReset());
  });

  it("asks before switching the page on, with the count it will show", async () => {
    api.getReviewSettings.mockResolvedValue(OFF);
    api.saveReviewSettings.mockResolvedValue({ ...OFF, reviews_public: true });
    renderBlock();
    const sw = await screen.findByRole("switch", { name: /Показывать отзывы на сайте/ });
    expect(screen.getByText("Опубликовано: 12")).toBeInTheDocument();
    fireEvent.click(sw);
    expect(screen.getByText(/появятся опубликованные отзывы: 12/)).toBeInTheDocument();
    expect(api.saveReviewSettings).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Включить" }));
    await waitFor(() => {
      expect(api.saveReviewSettings).toHaveBeenCalledWith(
        true,
        expect.stringMatching(/^admin-reviews-settings-/),
      );
    });
    expect(await screen.findByRole("switch", { checked: true })).toBeInTheDocument();
  });

  it("switches off at once", async () => {
    api.getReviewSettings.mockResolvedValue({ ...OFF, reviews_public: true });
    api.saveReviewSettings.mockResolvedValue(OFF);
    renderBlock();
    fireEvent.click(await screen.findByRole("switch", { name: /Показывать отзывы на сайте/ }));
    await waitFor(() => {
      expect(api.saveReviewSettings).toHaveBeenCalledWith(false, expect.any(String));
    });
  });
});
