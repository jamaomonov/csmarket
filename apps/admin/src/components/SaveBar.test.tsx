import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { countChanges, fieldsWord, SaveBar } from "./SaveBar";

describe("countChanges", () => {
  it("counts differing leaves, an added row by its cells", () => {
    const saved = { a: "1", b: { c: true }, rows: [{ x: "1", y: "2" }] };
    expect(countChanges(saved, saved)).toBe(0);
    expect(countChanges(saved, { ...saved, a: "2" })).toBe(1);
    expect(countChanges(saved, { ...saved, b: { c: false }, rows: [] })).toBe(3);
    expect(countChanges(saved, { ...saved, rows: [...saved.rows, { x: "", y: "" }] })).toBe(2);
  });
});

describe("fieldsWord", () => {
  it("agrees the noun with the number", () => {
    expect(fieldsWord(1)).toBe("1 поле");
    expect(fieldsWord(3)).toBe("3 поля");
    expect(fieldsWord(5)).toBe("5 полей");
    expect(fieldsWord(21)).toBe("21 поле");
  });
});

describe("SaveBar", () => {
  it("is hidden while nothing changed", () => {
    render(<SaveBar changed={0} saving={false} onSave={vi.fn()} onReset={vi.fn()} />);
    expect(screen.queryByRole("region", { name: "Несохранённые изменения" })).toBeNull();
  });

  it("names the count and saves or resets", () => {
    const onSave = vi.fn();
    const onReset = vi.fn();
    render(<SaveBar changed={2} saving={false} onSave={onSave} onReset={onReset} />);
    expect(screen.getByText("Изменено: 2 поля")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    fireEvent.click(screen.getByRole("button", { name: "Сбросить" }));
    expect(onSave).toHaveBeenCalledOnce();
    expect(onReset).toHaveBeenCalledOnce();
  });

  it("locks its buttons while saving", () => {
    render(<SaveBar changed={1} saving onSave={vi.fn()} onReset={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Сохранить" })).toBeDisabled();
  });
});
