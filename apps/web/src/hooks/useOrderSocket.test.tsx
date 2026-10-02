// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useOrderSocket } from "./useOrderSocket";

import type * as Realtime from "@/lib/realtime";
import type { OrderSocketOptions } from "@/lib/realtime";
import type { ReactNode } from "react";

interface AuthStub {
  status: string;
  user: { id: string } | null;
}

const m = vi.hoisted(() => ({
  auth: { value: null as AuthStub | null },
  opts: [] as OrderSocketOptions[],
  start: vi.fn(),
  stop: vi.fn(),
}));

vi.mock("@/lib/auth", () => ({ useAuth: () => m.auth.value }));
vi.mock("@/lib/api", () => ({
  API_BASE: "http://api.test",
  session: {
    getAccessToken: () => "tok",
    refreshAccessToken: () => Promise.resolve(true),
  },
}));
vi.mock("@/lib/realtime", async (importOriginal) => ({
  ...(await importOriginal<typeof Realtime>()),
  OrderSocket: class {
    constructor(opts: OrderSocketOptions) {
      m.opts.push(opts);
    }
    start = m.start;
    stop = m.stop;
  },
}));

function mount(client: QueryClient) {
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return renderHook(
    () => {
      useOrderSocket();
    },
    { wrapper },
  );
}

beforeEach(() => {
  m.auth.value = { status: "signed_in", user: { id: "u1" } };
  m.opts.length = 0;
  m.start.mockReset();
  m.stop.mockReset();
});

describe("useOrderSocket", () => {
  it("opens one socket for a signed-in buyer, on the API's socket URL", async () => {
    mount(new QueryClient());
    expect(m.start).toHaveBeenCalledTimes(1);
    expect(m.opts[0]?.url).toBe("ws://api.test/api/v1/realtime/orders");
    expect(await m.opts[0]?.getToken()).toBe("tok");
  });

  it("is not started for an anonymous visitor", () => {
    m.auth.value = { status: "anonymous", user: null };
    mount(new QueryClient());
    expect(m.start).not.toHaveBeenCalled();
  });

  it("a changed order invalidates exactly the order, the list, the balance and entries", () => {
    const client = new QueryClient();
    const spy = vi.spyOn(client, "invalidateQueries");
    mount(client);
    m.opts[0]?.onChanged("AB12CD34");
    const keys = spy.mock.calls.map(([filters]) => filters?.queryKey);
    expect(keys).toEqual([
      ["orders", "order", "AB12CD34"],
      ["orders", "list"],
      ["wallet", "balance"],
      ["wallet", "entries"],
    ]);
  });

  it("stops on unmount and on sign-out", () => {
    const { rerender, unmount } = mount(new QueryClient());
    m.auth.value = { status: "anonymous", user: null };
    rerender();
    expect(m.stop).toHaveBeenCalledTimes(1);
    m.auth.value = { status: "signed_in", user: { id: "u2" } };
    rerender();
    expect(m.start).toHaveBeenCalledTimes(2);
    unmount();
    expect(m.stop).toHaveBeenCalledTimes(2);
  });
});
