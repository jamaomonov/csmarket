// @vitest-environment jsdom
import { render } from "@testing-library/react";
import { expect, it } from "vitest";

import { ScrollActiveIntoView } from "./ScrollActiveIntoView";

// jsdom does no layout: give the row and its children sizes by hand.
function size(el: Element, props: Record<string, number>) {
  for (const [k, v] of Object.entries(props)) Object.defineProperty(el, k, { value: v });
}

it("centres the chosen chip, a menu chip ([data-active]) included", () => {
  const { container, rerender } = render(
    <ScrollActiveIntoView activeKey="" className="row">
      <a href="#">a</a>
      <span>menu</span>
    </ScrollActiveIntoView>,
  );
  const row = container.firstElementChild;
  if (!row) throw new Error("no row");
  size(row, { scrollWidth: 1000, clientWidth: 300 });
  const menu = row.querySelector("span");
  if (!menu) throw new Error("no menu chip");
  size(menu, { offsetLeft: 800, offsetWidth: 100 });
  menu.setAttribute("data-active", "");
  rerender(
    <ScrollActiveIntoView activeKey="cases" className="row">
      <a href="#">a</a>
      <span data-active="">menu</span>
    </ScrollActiveIntoView>,
  );
  expect(row.scrollLeft).toBe(700); // 800 − (300 − 100) / 2
});
