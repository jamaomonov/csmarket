// @vitest-environment jsdom
import { render } from "@testing-library/react";
import { expect, it } from "vitest";

import { SkinCategoryIcon } from "./SkinCategoryIcon";

const maskOf = (category: "knives" | "rifles") => {
  const { container } = render(<SkinCategoryIcon category={category} size="sm" />);
  return container.querySelector<HTMLElement>("[data-skin-icon]")?.style.maskSize;
};

it("the karambit is fitted by height, so its curve is never cropped", () => {
  expect(maskOf("knives")).toBe("auto 140%");
  expect(maskOf("rifles")).toBe("100% auto");
});
