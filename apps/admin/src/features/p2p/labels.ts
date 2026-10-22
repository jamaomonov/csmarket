/** Numbers of the «P2P» pages; statuses are `lib/dictionary`. */
/** `"70000.00"` → 70000 (whole soʻm; the journal keeps tiyin as the bank sent them). */
export function wholeSom(value: string | null): number {
  return value === null ? 0 : Math.trunc(Number(value));
}
