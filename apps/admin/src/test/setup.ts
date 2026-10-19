import "@testing-library/jest-dom/vitest";

// jsdom has no ResizeObserver; recharts' ResponsiveContainer needs one (it then draws at 0×0).
const noop = (): undefined => undefined;
if (!("ResizeObserver" in globalThis)) {
  Object.defineProperty(globalThis, "ResizeObserver", {
    value: class {
      observe = noop;
      unobserve = noop;
      disconnect = noop;
    },
  });
}
