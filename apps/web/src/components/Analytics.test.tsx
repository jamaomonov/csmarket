// @vitest-environment jsdom
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Analytics } from "./Analytics";

describe("Analytics", () => {
  it("loads no tag off csmarket.uz", () => {
    // jsdom runs on localhost, like `next dev` and the e2e stack.
    render(<Analytics />);
    expect(document.querySelector('script[src*="googletagmanager"]')).toBeNull();
  });
});
