/** Test helper: `useNarrow` sees a phone until the returned function restores `matchMedia`. */
export function asPhone(): () => void {
  const before = Object.getOwnPropertyDescriptor(window, "matchMedia");
  // Defined, not assigned: jsdom's `matchMedia` may be an accessor whose setter would keep the
  // fake behind the restored descriptor, leaving every later test on a phone.
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    writable: true,
    value: (query: string) => ({
      matches: true,
      media: query,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
    }),
  });
  return () => {
    if (before) Object.defineProperty(window, "matchMedia", before);
    else Reflect.deleteProperty(window, "matchMedia");
  };
}
