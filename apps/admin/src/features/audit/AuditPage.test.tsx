import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { type AuditRow } from "./api";
import { AuditPage } from "./AuditPage";

const api = vi.hoisted(() => ({ listAudit: vi.fn() }));
vi.mock("./api", () => api);

const ACTOR = { id: "a-1", display_name: "Boss" };
function row(over: Partial<AuditRow> & Pick<AuditRow, "id" | "action">): AuditRow {
  return {
    created_at: "2026-09-30T10:00:00Z",
    target_type: "user",
    target_id: "u-1",
    actor: ACTOR,
    payload: {},
    ...over,
  };
}

function renderPage(url = "/audit") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[url]}>
        <AuditPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("AuditPage", () => {
  beforeEach(() => {
    api.listAudit.mockReset();
  });

  it("labels every known action and falls back to the raw one", async () => {
    const known: [string, string][] = [
      ["users.ban", "Блокировка"],
      ["users.unban", "Разблокировка"],
      ["wallet.adjust", "Изменение баланса"],
      ["skins.item.hide", "Скин скрыт"],
      ["skins.item.unhide", "Скин показан"],
      ["skins.alias.put", "Синоним сохранён"],
      ["skins.alias.delete", "Синоним удалён"],
    ];
    api.listAudit.mockResolvedValue({
      items: [
        ...known.map(([action], i) => row({ id: `r-${String(i)}`, action })),
        row({ id: "r-x", action: "orders.cancel" }),
      ],
      next_cursor: null,
    });
    renderPage();
    const table = await screen.findByTestId("audit-table");
    // The «Действие» filter also lists the labels, so look inside the table only.
    for (const [, label] of known) {
      expect(within(table).getByText(label)).toBeInTheDocument();
    }
    expect(within(table).getByText("orders.cancel")).toBeInTheDocument();
  });

  it("shows who, the target link and the payload as key: value", async () => {
    api.listAudit.mockResolvedValue({
      items: [
        row({
          id: "r-1",
          action: "wallet.adjust",
          payload: { amount_uzs: -20000, reason: "Ошибка" },
        }),
        row({
          id: "r-2",
          action: "skins.alias.put",
          target_type: "skin_alias",
          target_id: "ak",
          payload: { alias: "ak", text: "ak-47" },
        }),
      ],
      next_cursor: null,
    });
    renderPage();
    await screen.findByTestId("audit-table");
    const [adjust, alias] = screen.getAllByRole("row").slice(1) as [HTMLElement, HTMLElement];
    expect(within(adjust).getByRole("link", { name: "Boss" })).toHaveAttribute(
      "href",
      "/users/a-1",
    );
    expect(within(adjust).getByRole("link", { name: /Пользователь/ })).toHaveAttribute(
      "href",
      "/users/u-1",
    );
    expect(within(adjust).getByText(/сумма: −20\s000 сум/)).toBeInTheDocument();
    expect(within(adjust).getByText("причина: Ошибка")).toBeInTheDocument();
    // A skin alias has no page of its own: plain text.
    expect(within(alias).getAllByRole("link")).toHaveLength(1); // the actor only
    expect(within(alias).getByText("ak", { selector: "span.font-mono" })).toBeInTheDocument();
    expect(within(alias).getByText("значение: ak-47")).toBeInTheDocument();
  });

  it("names targets instead of showing their UUIDs", async () => {
    const uuid = "6f1c2a52-0000-4000-8000-000000000001";
    api.listAudit.mockResolvedValue({
      items: [
        row({ id: "r-1", action: "users.ban", target_id: uuid, target_label: "Ivan" }),
        row({
          id: "r-2",
          action: "skins.item.hide",
          target_type: "skin_item",
          target_id: uuid,
          target_label: "AK-47 | Redline (Field-Tested)",
          payload: { slug: "ak-47-redline-field-tested" },
        }),
        row({
          id: "r-3",
          action: "sales.payout.paid",
          target_type: "payout_request",
          target_id: uuid,
          target_label: "S7K2M9QX",
        }),
        row({
          id: "r-4",
          action: "payments.hold.release",
          target_type: "payment_hold",
          target_id: uuid,
          payload: { number: "P100001", user_id: uuid },
        }),
        row({ id: "r-5", action: "users.unban", target_id: uuid, target_label: null }),
      ],
      next_cursor: null,
    });
    renderPage();
    const table = await screen.findByTestId("audit-table");
    expect(table).not.toHaveTextContent(uuid);
    expect(table).not.toHaveTextContent("slug");
    const [user, skin, payout, hold, nameless] = within(table).getAllByRole("row").slice(1) as [
      HTMLElement,
      HTMLElement,
      HTMLElement,
      HTMLElement,
      HTMLElement,
    ];
    expect(within(user).getByRole("link", { name: "Пользователь Ivan" })).toHaveAttribute(
      "href",
      `/users/${uuid}`,
    );
    expect(skin).toHaveTextContent("Скин AK-47 | Redline (Field-Tested)");
    expect(within(payout).getByRole("link", { name: "Выплата S7K2M9QX" })).toHaveAttribute(
      "href",
      `/payouts/${uuid}`,
    );
    expect(hold).toHaveTextContent("Платёж на проверке P100001");
    expect(hold).not.toHaveTextContent("номер");
    expect(within(nameless).getByRole("link", { name: "Пользователь" })).toBeInTheDocument();
  });

  it("translates payload keys and values, an unknown key stays small", async () => {
    api.listAudit.mockResolvedValue({
      items: [
        row({
          id: "r-1",
          action: "skins.pricing.save",
          target_type: "skin_pricing_rules",
          target_id: "1",
          payload: { items_repriced: 12, enabled: "false -> true", flux: "on" },
        }),
        row({ id: "r-2", action: "orders.teleport" }),
      ],
      next_cursor: null,
    });
    renderPage();
    const table = await screen.findByTestId("audit-table");
    expect(within(table).getByText("цены пересчитаны у скинов: 12")).toBeInTheDocument();
    expect(within(table).getByText("включено: нет → да")).toBeInTheDocument();
    expect(within(table).getByText("flux")).toHaveClass("text-meta");
    expect(within(table).getByText("другое действие")).toBeInTheDocument();
    expect(within(table).getByText("orders.teleport")).toHaveClass("text-meta");
  });

  it("filters by action, target type and target id", async () => {
    api.listAudit.mockResolvedValue({ items: [], next_cursor: null });
    renderPage();
    fireEvent.change(await screen.findByLabelText("Действие"), {
      target: { value: "users.ban" },
    });
    await waitFor(() => {
      expect(api.listAudit).toHaveBeenLastCalledWith({ action: "users.ban" });
    });
    fireEvent.change(screen.getByLabelText("Тип цели"), { target: { value: "user" } });
    await waitFor(() => {
      expect(api.listAudit).toHaveBeenLastCalledWith({ action: "users.ban", target_type: "user" });
    });
    fireEvent.change(screen.getByLabelText("Id цели"), { target: { value: " u-1 " } });
    await waitFor(() => {
      expect(api.listAudit).toHaveBeenLastCalledWith({
        action: "users.ban",
        target_type: "user",
        target_id: "u-1",
      });
    });
    expect(await screen.findByText("Записей нет.")).toBeInTheDocument();
  });

  it("the filters are one row of compact selects and a plain search", async () => {
    api.listAudit.mockResolvedValue({ items: [], next_cursor: null });
    renderPage();
    expect(await screen.findByRole("option", { name: "Действие: все" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Тип цели: все" })).toBeInTheDocument();
    expect(screen.getByRole("searchbox", { name: "Id цели" })).not.toHaveClass("font-mono");
  });

  it("drops unknown options and an over-long id from a hand-edited URL", async () => {
    api.listAudit.mockResolvedValue({ items: [], next_cursor: null });
    renderPage(`/audit?action=orders.nope&target_type=planet&target_id=${"x".repeat(65)}`);
    expect(await screen.findByText("Записей нет.")).toBeInTheDocument();
    expect(api.listAudit).toHaveBeenCalledWith({});
    expect(screen.getByLabelText("Действие")).toHaveValue("");
    expect(screen.getByLabelText("Id цели")).toHaveValue("");
  });

  it("keeps known options and an id within the limit from the URL", async () => {
    api.listAudit.mockResolvedValue({ items: [], next_cursor: null });
    renderPage(`/audit?action=users.ban&target_type=user&target_id=${"x".repeat(64)}`);
    expect(await screen.findByText("Записей нет.")).toBeInTheDocument();
    expect(api.listAudit).toHaveBeenCalledWith({
      action: "users.ban",
      target_type: "user",
      target_id: "x".repeat(64),
    });
  });

  it("loads the next page behind «Показать ещё»", async () => {
    api.listAudit
      .mockResolvedValueOnce({ items: [row({ id: "r-1", action: "users.ban" })], next_cursor: "c" })
      .mockResolvedValueOnce({
        items: [row({ id: "r-2", action: "users.unban" })],
        next_cursor: null,
      });
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Показать ещё" }));
    expect(
      await within(screen.getByTestId("audit-table")).findByText("Разблокировка"),
    ).toBeInTheDocument();
    expect(api.listAudit).toHaveBeenLastCalledWith({ cursor: "c" });
  });
});
