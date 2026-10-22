/** Test helper: `useNarrow` sees a phone until the returned function restores `matchMedia`. */
export function asPhone(): () => void {
  const before = Object.getOwnPropertyDescriptor(window, "matchMedia");
  window.matchMedia = ((query: string) => ({
    matches: true,
    media: query,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  })) as unknown as typeof window.matchMedia; // only the members useNarrow reads
  return () => {
    if (before) Object.defineProperty(window, "matchMedia", before);
    else Reflect.deleteProperty(window, "matchMedia");
  };
}
