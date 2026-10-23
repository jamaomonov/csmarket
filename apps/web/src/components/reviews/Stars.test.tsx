// @vitest-environment jsdom
import common from "@csmarket/i18n/locales/ru/common.json";
import ru from "@csmarket/i18n/locales/ru/web.json";
import { fireEvent, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import { Stars } from "./Stars";

const show = (node: React.ReactNode) =>
  render(
    <NextIntlClientProvider locale="ru" messages={{ web: ru, common }}>
      {node}
    </NextIntlClientProvider>,
  );

describe("Stars", () => {
  it("picked: native radios under one name (one Tab stop, arrow keys)", () => {
    const onChange = vi.fn();
    show(<Stars value={3} onChange={onChange} />);
    const radios = screen.getAllByRole<HTMLInputElement>("radio");
    expect(radios.map((r) => r.type)).toEqual(Array(5).fill("radio"));
    expect(new Set(radios.map((r) => r.name)).size).toBe(1);
    expect(screen.getByRole("radio", { name: "3 звезды" })).toBeChecked();
    fireEvent.click(screen.getByRole("radio", { name: "5 звёзд" }));
    expect(onChange).toHaveBeenCalledWith(5);
  });

  it("lights up to the hovered star", () => {
    show(<Stars value={1} onChange={vi.fn()} />);
    const star = (n: number) => screen.getAllByRole("radio")[n - 1]?.parentElement;
    fireEvent.mouseEnter(star(4) as Element);
    expect(star(4)?.querySelector("svg")).toHaveClass("fill-warning");
    fireEvent.mouseLeave(screen.getByRole("radiogroup"));
    expect(star(4)?.querySelector("svg")).not.toHaveClass("fill-warning");
  });

  it("shown: one picture named «Оценка 4 из 5»", () => {
    show(<Stars value={4} />);
    expect(screen.getByRole("img", { name: "Оценка 4 из 5" })).toBeInTheDocument();
  });
});
