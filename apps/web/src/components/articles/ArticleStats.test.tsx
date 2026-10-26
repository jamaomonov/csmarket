// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("@/lib/api", () => ({ session: { api } }));
vi.mock("next-intl", () => ({
  useTranslations: () => (key: string, v?: { n?: number }) =>
    v?.n === undefined ? key : `${key}:${String(v.n)}`,
}));

import { ArticleStats } from "./ArticleStats";

describe("ArticleStats", () => {
  beforeEach(() => {
    api.mockReset();
  });

  it("shows my counters and likes on a press", async () => {
    api
      .mockResolvedValueOnce({ likes: 4, liked: false, views: 12 })
      .mockResolvedValueOnce({ likes: 5, liked: true });
    render(<ArticleStats slug="top" likes={4} views={10} />);
    expect(await screen.findByText("views:12")).toBeInTheDocument();
    const button = screen.getByRole("button", { name: "like" });
    expect(button).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(button);
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "unlike" })).toHaveAttribute(
        "aria-pressed",
        "true",
      );
    });
    expect(screen.getByText("5")).toBeInTheDocument();
    expect(api).toHaveBeenLastCalledWith("/api/v1/articles/top/like", { method: "PUT" });
  });

  it("rolls back when the like fails", async () => {
    api
      .mockResolvedValueOnce({ likes: 4, liked: false, views: 1 })
      .mockRejectedValueOnce(new Error("429"));
    render(<ArticleStats slug="top" likes={4} views={1} />);
    await screen.findByText("views:1");
    fireEvent.click(screen.getByRole("button", { name: "like" }));
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "like" })).toHaveAttribute("aria-pressed", "false");
    });
    expect(screen.getByText("4")).toBeInTheDocument();
  });

  it("unlikes with DELETE", async () => {
    api
      .mockResolvedValueOnce({ likes: 1, liked: true, views: 1 })
      .mockResolvedValueOnce({ likes: 0, liked: false });
    render(<ArticleStats slug="top" likes={1} views={1} />);
    fireEvent.click(await screen.findByRole("button", { name: "unlike" }));
    await waitFor(() => {
      expect(api).toHaveBeenLastCalledWith("/api/v1/articles/top/like", { method: "DELETE" });
    });
  });
});
