import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { type PricingRules } from "./api";
import { PRICING, QUOTE } from "./fixtures";
import { PricingPage } from "./PricingPage";

import { ApiError } from "@/lib/api";

const api = vi.hoisted(() => ({
  getPricing: vi.fn(),
  savePricing: vi.fn(),
  previewPrice: vi.fn(),
  findPricedItems: vi.fn(),
  saveItemPricing: vi.fn(),
}));
vi.mock("./api", () => api);

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <PricingPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const field = (label: string): HTMLInputElement => screen.getByLabelText(label);

async function typeExpenses(value: string): Promise<void> {
  const input = await screen.findByLabelText("Расходы, %");
  fireEvent.change(input, { target: { value } });
}

describe("PricingPage", () => {
  beforeEach(() => {
    Object.values(api).forEach((f) => f.mockReset());
    api.getPricing.mockResolvedValue(PRICING);
    api.previewPrice.mockResolvedValue(QUOTE);
    api.findPricedItems.mockResolvedValue({ items: [] });
  });

  it("says what the rules price, at what rate, and who saved them", async () => {
    renderPage();
    const status = await screen.findByTestId("pricing-status");
    expect(status).toHaveTextContent("Активных скинов: 21 000");
    expect(status).toHaveTextContent("с ручной ценой: 4");
    expect(status).toHaveTextContent("курс: 12 700 сум за $1");
    expect(status).toHaveTextContent("правила обновил Жамшид");
  });

  it("saves the whole document once, with a key, after the confirm", async () => {
    api.savePricing.mockResolvedValue(PRICING);
    renderPage();
    await typeExpenses("5");
    expect(screen.getByText("Есть несохранённые изменения")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    expect(screen.getByRole("dialog", { name: "Сохранить наценки?" })).toBeInTheDocument();
    expect(api.savePricing).not.toHaveBeenCalled();
    const yes = screen.getByRole("button", { name: "Да, сохранить" });
    fireEvent.click(yes);
    fireEvent.click(yes);
    await waitFor(() => {
      expect(api.savePricing).toHaveBeenCalledTimes(1);
    });
    const [rules, key] = api.savePricing.mock.calls[0] as [PricingRules, string];
    expect(rules).toEqual({ ...PRICING.rules, expenses_percent: "5" });
    expect(key.length).toBeGreaterThanOrEqual(16);
  });

  it("a refused document is explained in Russian and the typed values stay", async () => {
    api.savePricing.mockRejectedValue(
      new ApiError(422, "Unprocessable", {
        detail: [{ msg: "Value error, retail: the first bracket must start at 0" }],
      }),
    );
    renderPage();
    await typeExpenses("7");
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    fireEvent.click(screen.getByRole("button", { name: "Да, сохранить" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Проверьте числа: брекеты должны идти по возрастанию от $0.",
    );
    expect(field("Расходы, %").value).toBe("7");
    expect(screen.queryByText(/first bracket/)).not.toBeInTheDocument();
  });

  it("previews with the unsaved form values", async () => {
    renderPage();
    await typeExpenses("9");
    fireEvent.change(screen.getByLabelText("Себестоимость, $"), { target: { value: "10" } });
    fireEvent.change(screen.getByLabelText("Категория"), { target: { value: "rifles" } });
    await act(async () => {
      await new Promise((r) => setTimeout(r, 350));
    });
    await waitFor(() => {
      const bodies = api.previewPrice.mock.calls.map(([b]) => b as { rules: PricingRules });
      expect(bodies.some((b) => b.rules.expenses_percent === "9")).toBe(true);
    });
    expect(await screen.findByText("$11.55")).toBeInTheDocument();
    expect(screen.getByText("по формуле")).toBeInTheDocument();
  });

  it("resets the form to the saved document", async () => {
    renderPage();
    await typeExpenses("8");
    fireEvent.click(screen.getByRole("button", { name: "Сбросить" }));
    expect(field("Расходы, %").value).toBe("3");
    expect(screen.queryByText("Есть несохранённые изменения")).not.toBeInTheDocument();
  });
});
