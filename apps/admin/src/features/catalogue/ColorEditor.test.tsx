import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ColorEditor } from "./ColorEditor";

import type { AdminSkinItem } from "./api";

const api = vi.hoisted(() => ({ setColors: vi.fn() }));
vi.mock("./api", async (importOriginal) => ({ ...(await importOriginal<object>()), ...api }));

const ITEM: AdminSkinItem = {
  slug: "ak-47-redline-field-tested",
  name: "AK-47 | Redline (Field-Tested)",
  phase: null,
  category: "rifles",
  weapon: "AK-47",
  exterior: "FT",
  stattrak: false,
  souvenir: false,
  image_url: null,
  active: true,
  hidden: false,
  price_usd: "27",
  count: 3,
  colors: ["grey"],
  colors_manual: false,
};

function renderEditor(item: AdminSkinItem = ITEM) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <ColorEditor item={item} />
    </QueryClientProvider>,
  );
}

describe("ColorEditor", () => {
  beforeEach(() => {
    api.setColors.mockReset().mockResolvedValue(ITEM);
  });

  it("shows the colours and sets new ones, two at most", async () => {
    renderEditor();
    expect(screen.getByText("Серый")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Цвет" }));
    fireEvent.click(screen.getByRole("button", { name: "Серый" })); // grey off
    for (const name of ["Красный", "Чёрный", "Белый"]) {
      fireEvent.click(screen.getByRole("button", { name }));
    }
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    await waitFor(() => {
      expect(api.setColors).toHaveBeenCalledWith(ITEM.slug, ["black", "white"]);
    });
  });

  it("gives the colours back to the job", async () => {
    renderEditor({ ...ITEM, colors_manual: true });
    expect(screen.getByText("· вручную")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Цвет" }));
    fireEvent.click(screen.getByRole("button", { name: "Авто" }));
    await waitFor(() => {
      expect(api.setColors).toHaveBeenCalledWith(ITEM.slug, null);
    });
  });
});
