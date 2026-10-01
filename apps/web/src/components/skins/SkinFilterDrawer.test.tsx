// @vitest-environment jsdom
import common from "@csmarket/i18n/locales/ru/common.json";
import messages from "@csmarket/i18n/locales/ru/web.json";
import { fireEvent, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { expect, it, vi } from "vitest";

import { SkinFilterDrawer } from "./SkinFilterDrawer";

vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

function drawer() {
  render(
    <NextIntlClientProvider locale="ru" messages={{ web: messages, common }}>
      <SkinFilterDrawer count={0}>
        <button type="button">После полевых</button>
      </SkinFilterDrawer>
    </NextIntlClientProvider>,
  );
  return screen.getByRole("button", { name: "Фильтры" });
}

it("moves focus into the drawer on open and back to the trigger on close", () => {
  const trigger = drawer();
  fireEvent.click(trigger);
  const dialog = screen.getByRole("dialog");
  expect(dialog).toContainElement(document.activeElement as HTMLElement);
  fireEvent.keyDown(document, { key: "Escape" });
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(trigger).toHaveFocus();
});

it("keeps the backdrop out of the tab order and names one close control", () => {
  fireEvent.click(drawer());
  expect(screen.getAllByRole("button", { name: "Готово" })).toHaveLength(1);
});

it("restores the page's own overflow lock on close", () => {
  document.body.style.overflow = "clip";
  fireEvent.click(drawer());
  fireEvent.keyDown(document, { key: "Escape" });
  expect(document.body.style.overflow).toBe("clip");
  document.body.style.overflow = "";
});
