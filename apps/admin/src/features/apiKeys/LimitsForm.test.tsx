import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { LimitsForm } from "./LimitsForm";

const api = vi.hoisted(() => ({ setApiKeyLimits: vi.fn() }));
vi.mock("./api", () => api);

const IDEM = { keyFor: () => "admin-key-limits-0123456789abcdef", reset: vi.fn() };

function renderForm(current = {}) {
  const onDone = vi.fn();
  const qc = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <LimitsForm keyId="k-1" current={current} idem={IDEM} onDone={onDone} onClose={vi.fn()} />
    </QueryClientProvider>,
  );
  return onDone;
}

describe("LimitsForm", () => {
  beforeEach(() => {
    api.setApiKeyLimits.mockReset();
  });

  it("shows the defaults as placeholders", () => {
    renderForm();
    expect(screen.getByLabelText("Чтение")).toHaveAttribute("placeholder", "60 (по умолчанию)");
    expect(screen.getByLabelText("Заказы")).toHaveAttribute("placeholder", "10 (по умолчанию)");
    expect(screen.getByLabelText("Фид")).toHaveAttribute("placeholder", "1 (по умолчанию)");
    expect(screen.getByLabelText("Проверка трейд-ссылки")).toHaveAttribute(
      "placeholder",
      "30 (по умолчанию)",
    );
  });

  it("sends the typed value and null for empty fields", async () => {
    api.setApiKeyLimits.mockResolvedValue({ key: {} });
    const onDone = renderForm();
    fireEvent.change(screen.getByLabelText("Чтение"), { target: { value: "600" } });
    fireEvent.change(screen.getByLabelText("Причина"), { target: { value: "витрина" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    await waitFor(() => {
      expect(api.setApiKeyLimits).toHaveBeenCalledTimes(1);
    });
    expect(api.setApiKeyLimits).toHaveBeenCalledWith(
      "k-1",
      {
        read_per_min: 600,
        orders_per_min: null,
        feed_per_min: null,
        check_per_min: null,
        reason: "витрина",
      },
      "admin-key-limits-0123456789abcdef",
    );
    await waitFor(() => {
      expect(onDone).toHaveBeenCalled();
    });
  });

  it("refuses a value out of range or a missing reason", () => {
    renderForm();
    fireEvent.change(screen.getByLabelText("Чтение"), { target: { value: "0" } });
    fireEvent.change(screen.getByLabelText("Причина"), { target: { value: "витрина" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    expect(screen.getByRole("alert")).toHaveTextContent("от 1 до 10000");
    fireEvent.change(screen.getByLabelText("Чтение"), { target: { value: "5" } });
    fireEvent.change(screen.getByLabelText("Причина"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    expect(screen.getByRole("alert")).toHaveTextContent("причину");
    expect(api.setApiKeyLimits).not.toHaveBeenCalled();
  });
});
