import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { requestHeaders, unstableCache } = vi.hoisted(() => ({
  requestHeaders: { value: new Headers() },
  unstableCache: vi.fn((fn: () => Promise<unknown>, _key: string[], _opts: unknown) => () => fn()),
}));

vi.mock("next/headers", () => ({ headers: () => Promise.resolve(requestHeaders.value) }));
vi.mock("next/cache", () => ({ unstable_cache: unstableCache }));

import {
  apiGet,
  storefrontHeaders,
  STOREFRONT_CLIENT_IP_HEADER,
  STOREFRONT_SECRET_HEADER,
  visitorIp,
} from "./server-api";

const SECRET = "test-storefront-secret-not-a-real-one-0123";
const VISITOR = "198.51.100.23";

const ok = () =>
  new Response("{}", { status: 200, headers: { "Content-Type": "application/json" } });

type Init = RequestInit & { headers: Record<string, string>; next?: unknown };

function stubFetch() {
  const f = vi.fn().mockImplementation(() => Promise.resolve(ok()));
  vi.stubGlobal("fetch", f);
  return () => f.mock.calls[0]?.[1] as Init; // the init the API call was made with
}

describe("visitorIp", () => {
  it("takes the first X-Forwarded-For entry", () => {
    expect(visitorIp(new Headers({ "X-Forwarded-For": `${VISITOR}, 10.0.0.2` }))).toBe(VISITOR);
    expect(visitorIp(new Headers({ "x-forwarded-for": "2001:db8::7" }))).toBe("2001:db8::7");
  });

  it("is null when there is no usable address", () => {
    expect(visitorIp(new Headers())).toBeNull();
    expect(visitorIp(new Headers({ "X-Forwarded-For": "  " }))).toBeNull();
    expect(visitorIp(new Headers({ "X-Forwarded-For": "unknown" }))).toBeNull();
  });
});

describe("storefrontHeaders", () => {
  it("names the visitor beside the secret", () => {
    expect(storefrontHeaders(VISITOR, SECRET)).toEqual({
      [STOREFRONT_SECRET_HEADER]: SECRET,
      [STOREFRONT_CLIENT_IP_HEADER]: VISITOR,
    });
  });

  it("sends nothing without a secret or a visitor", () => {
    expect(storefrontHeaders(VISITOR, "")).toEqual({});
    expect(storefrontHeaders(VISITOR, undefined)).toEqual({});
    expect(storefrontHeaders(null, SECRET)).toEqual({});
  });
});

describe("apiGet", () => {
  beforeEach(() => {
    vi.stubEnv("CSMARKET_STOREFRONT_SECRET", SECRET);
    requestHeaders.value = new Headers({ "X-Forwarded-For": VISITOR });
    unstableCache.mockClear();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it("a perVisitor uncached call carries the visitor", async () => {
    const init = stubFetch();
    await apiGet("/skins/ak", { noStore: true, perVisitor: true });
    expect(init().headers[STOREFRONT_CLIENT_IP_HEADER]).toBe(VISITOR);
    expect(init().headers[STOREFRONT_SECRET_HEADER]).toBe(SECRET);
    expect(init().cache).toBe("no-store");
  });

  it("a perVisitor cached call keeps one cache entry for every visitor", async () => {
    const init = stubFetch();
    await apiGet("/skins/catalog?q=ak", { perVisitor: true, revalidate: 30 });
    // The shared entry is keyed by the path; the visitor rides only on the miss's fetch.
    expect(unstableCache).toHaveBeenCalledWith(
      expect.any(Function),
      ["server-api", "/skins/catalog?q=ak"],
      { revalidate: 30, tags: ["skins"] },
    );
    expect(init().headers[STOREFRONT_CLIENT_IP_HEADER]).toBe(VISITOR);
    expect(init().cache).toBe("no-store");
  });

  it("a call not made perVisitor sends no visitor and uses the fetch cache", async () => {
    const init = stubFetch();
    await apiGet("/skins/facets");
    expect(init().headers).toEqual({ Accept: "application/json" });
    expect(init().next).toEqual({ revalidate: 60, tags: ["skins"] });
    expect(unstableCache).not.toHaveBeenCalled();
  });

  it("without the secret configured nothing changes", async () => {
    vi.stubEnv("CSMARKET_STOREFRONT_SECRET", "");
    const init = stubFetch();
    await apiGet("/skins/catalog?q=ak", { perVisitor: true });
    expect(init().headers).toEqual({ Accept: "application/json" });
    expect(init().next).toEqual({ revalidate: 60, tags: ["skins"] });
    expect(unstableCache).not.toHaveBeenCalled();
  });
});
