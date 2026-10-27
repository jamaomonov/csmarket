// @vitest-environment jsdom
import { render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { RefCapture } from "./RefCapture";

describe("RefCapture", () => {
  const fetchMock = vi.fn(() => Promise.resolve(new Response(null, { status: 204 })));

  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
    fetchMock.mockClear();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    window.history.replaceState(null, "", "/");
  });

  it("remembers a partner's link once and takes ref out of the address", () => {
    window.history.replaceState(null, "", "/market?sort=price&ref=zufarmax#top");
    render(<RefCapture />);
    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toMatch(/\/api\/v1\/referrals\/visit$/);
    expect(init.method).toBe("POST");
    expect(init.credentials).toBe("include");
    expect(JSON.parse(init.body as string)).toEqual({ code: "zufarmax" }); // the body we built is a JSON string
    expect(window.location.pathname + window.location.search + window.location.hash).toBe(
      "/market?sort=price#top",
    );
  });

  it("ignores a malformed code but still cleans the address", () => {
    window.history.replaceState(null, "", "/?ref=Bad%20Code!");
    render(<RefCapture />);
    expect(fetchMock).not.toHaveBeenCalled();
    expect(window.location.search).toBe("");
  });

  it("does nothing without ref", () => {
    window.history.replaceState(null, "", "/market?sort=price");
    render(<RefCapture />);
    expect(fetchMock).not.toHaveBeenCalled();
    expect(window.location.search).toBe("?sort=price");
  });
});
