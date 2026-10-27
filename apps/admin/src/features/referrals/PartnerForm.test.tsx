import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PARTNER } from "./fixtures";
import { PartnerForm } from "./PartnerForm";

import { ApiError } from "@/lib/api";

const api = vi.hoisted(() => ({ createPartner: vi.fn(), updatePartner: vi.fn() }));
vi.mock("./api", async (importOriginal) => ({ ...(await importOriginal<object>()), ...api }));

const onDone = vi.fn();

function renderForm(props: Parameters<typeof PartnerForm>[0]) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <PartnerForm {...props} />
    </QueryClientProvider>,
  );
}

describe("PartnerForm", () => {
  beforeEach(() => {
    api.createPartner.mockReset().mockResolvedValue(PARTNER);
    api.updatePartner.mockReset().mockResolvedValue(PARTNER);
    onDone.mockReset();
  });

  it("warns about the margin above 2 %", () => {
    renderForm({ userId: "u1", onDone });
    const percent = screen.getByLabelText("Процент с покупок");
    fireEvent.change(percent, { target: { value: "2" } });
    expect(screen.queryByText(/маржа может уйти в минус/)).toBeNull();
    fireEvent.change(percent, { target: { value: "2.1" } });
    expect(screen.getByRole("status")).toHaveTextContent(
      "На скинах от $1 000 маржа может уйти в минус.",
    );
  });

  it("creates a partner with «Навсегда» as a null term", async () => {
    renderForm({ userId: "u1", onDone });
    fireEvent.change(screen.getByLabelText("Код ссылки"), { target: { value: "zufarmax" } });
    fireEvent.change(screen.getByLabelText("Процент с покупок"), { target: { value: "1.5" } });
    fireEvent.click(screen.getByRole("checkbox", { name: "Навсегда" }));
    fireEvent.click(screen.getByRole("button", { name: "Сделать партнёром" }));
    await waitFor(() => {
      expect(api.createPartner).toHaveBeenCalled();
    });
    const [userId, body] = api.createPartner.mock.calls[0] as [string, Record<string, unknown>];
    expect(userId).toBe("u1");
    expect(body).toEqual({ code: "zufarmax", percent: "1.5", term_months: null, note: null });
    await waitFor(() => {
      expect(onDone).toHaveBeenCalledWith(PARTNER);
    });
  });

  it("locks the code once people came by it", () => {
    renderForm({ partner: PARTNER, onDone });
    expect(screen.getByLabelText("Код ссылки")).toBeDisabled();
    expect(screen.getByText(/Код нельзя менять/)).toBeInTheDocument();
  });

  it("sends only what changed when editing", async () => {
    renderForm({ partner: PARTNER, onDone });
    fireEvent.click(screen.getByRole("checkbox", { name: "Активен" }));
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    await waitFor(() => {
      expect(api.updatePartner).toHaveBeenCalled();
    });
    const [, patch] = api.updatePartner.mock.calls[0] as [string, Record<string, unknown>];
    expect(patch).toEqual({ active: false });
  });

  it("explains a taken code", async () => {
    api.createPartner.mockRejectedValue(
      new ApiError(409, "Conflict", { code: "code_taken", detail: "x" }),
    );
    renderForm({ userId: "u1", onDone });
    fireEvent.change(screen.getByLabelText("Код ссылки"), { target: { value: "zufarmax" } });
    fireEvent.change(screen.getByLabelText("Процент с покупок"), { target: { value: "1" } });
    fireEvent.click(screen.getByRole("button", { name: "Сделать партнёром" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Такой код уже занят.");
  });
});
