import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { DataTable } from "./DataTable";
import { Money, formatMoneyUsd } from "./Money";
import { StatusChip } from "./StatusChip";
import { Tabs } from "./Tabs";

interface Row {
  id: string;
  name: string;
  sum: string;
}
const COLUMNS = [
  { key: "name", header: "Имя", cell: (r: Row) => r.name },
  { key: "sum", header: "Сумма", align: "right" as const, cell: (r: Row) => r.sum },
];

describe("formatMoneyUsd", () => {
  it("pads to two places, groups digits, uses a typographic minus", () => {
    expect(formatMoneyUsd("1.1")).toBe("$1.10");
    expect(formatMoneyUsd("1.100000")).toBe("$1.10");
    expect(formatMoneyUsd("12345.5")).toBe("$12 345.50");
    expect(formatMoneyUsd("-2")).toBe("−$2.00");
    expect(formatMoneyUsd("7.826", 3)).toBe("$7.826");
  });
});

describe("Money", () => {
  it("colours a negative amount and signs a positive one", () => {
    render(<Money usd="-1" />);
    expect(screen.getByText("−$1.00")).toHaveClass("text-danger");
    render(<Money uzs="5000" signed />);
    expect(screen.getByText(/^\+5/)).toBeInTheDocument();
  });
});

describe("StatusChip", () => {
  it("renders the second line", () => {
    render(
      <StatusChip tone="info" sub="6д 4ч · 15.10" testId="chip">
        на холде
      </StatusChip>,
    );
    expect(screen.getByTestId("chip")).toHaveTextContent("на холде");
    expect(screen.getByText("6д 4ч · 15.10")).toBeInTheDocument();
  });
});

describe("Tabs", () => {
  it("marks the current tab and reports a click", () => {
    const onChange = vi.fn();
    render(
      <Tabs
        label="Вид"
        value="all"
        onChange={onChange}
        items={[
          { key: "all", label: "Все", count: 3 },
          { key: "attention", label: "Внимание", count: 1, alert: true },
        ]}
      />,
    );
    expect(screen.getByRole("tab", { name: /Все/ })).toHaveAttribute("aria-selected", "true");
    fireEvent.click(screen.getByRole("tab", { name: /Внимание/ }));
    expect(onChange).toHaveBeenCalledWith("attention");
  });
});

describe("DataTable", () => {
  it("renders headers apart and right-aligns numbers", () => {
    render(
      <DataTable
        label="t"
        columns={COLUMNS}
        rows={[{ id: "1", name: "A", sum: "10" }]}
        rowKey={(r) => r.id}
      />,
    );
    const headers = screen.getAllByRole("columnheader");
    expect(headers.map((h) => h.textContent)).toEqual(["Имя", "Сумма"]);
    expect(headers[1]).toHaveClass("text-right");
    expect(screen.getByRole("table")).toHaveAttribute("aria-label", "t");
  });

  it("shows the empty and error states", () => {
    const { rerender } = render(
      <DataTable label="t" columns={COLUMNS} rows={[]} rowKey={(r) => r.id} empty="Пусто" />,
    );
    expect(screen.getByText("Пусто")).toBeInTheDocument();
    rerender(<DataTable label="t" columns={COLUMNS} rows={[]} rowKey={(r) => r.id} error="Сбой" />);
    expect(screen.getByRole("alert")).toHaveTextContent("Сбой");
  });

  it("opens a row on click but lets a link inside do its own thing", () => {
    const onRowClick = vi.fn();
    render(
      <MemoryRouter>
        <DataTable
          label="t"
          columns={[...COLUMNS, { key: "l", header: "", cell: () => <a href="#x">ссылка</a> }]}
          rows={[{ id: "1", name: "A", sum: "10" }]}
          rowKey={(r) => r.id}
          onRowClick={onRowClick}
        />
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByText("ссылка"));
    expect(onRowClick).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText("A"));
    expect(onRowClick).toHaveBeenCalledTimes(1);
  });
});
