/**
 * Guards for filter values read from the address bar. A hand-edited or stale URL must not
 * reach the API as a value the page could never have written: an unknown option is dropped,
 * and so is free text longer than its input allows (the API would answer 422).
 */

/** The value if it is one of `allowed`, else `undefined`. */
export function pick<T extends string>(allowed: readonly T[], value: string): T | undefined {
  return allowed.find((a) => a === value);
}

/** The value if it is at most `max` characters long, else `""` (no filter). */
export function upTo(value: string, max: number): string {
  return value.length <= max ? value : "";
}
