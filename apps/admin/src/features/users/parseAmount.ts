/**
 * Parsing for the admin balance-adjustment amount.
 *
 * This field creates money: a positive value credits the customer, a negative
 * one claws it back. Balances are whole soʻm, so the parser is deliberately
 * strict — an optional sign and digits, with spaces allowed as thousands
 * separators (including the no-break spaces a formatted table pastes). It
 * rejects `1e9`, `--5`, decimals and stray letters rather than guessing.
 */

const WHOLE_SIGNED = /^[+-]?\d+$/;

/**
 * Parse operator input into whole soʻm.
 *
 * @param input - What the operator typed, e.g. `"50 000"` or `"-10000"`.
 * @returns The signed amount (`0` stays `0`; the form explains why it is
 *   refused), or `null` when the input is not a whole number of soʻm.
 */
export function parseAmount(input: string): number | null {
  // `\s` covers the no-break (U+00A0) and narrow no-break (U+202F) spaces.
  const normalised = input.replace(/\s/g, "");
  if (!WHOLE_SIGNED.test(normalised)) return null;
  const value = Number(normalised);
  if (!Number.isSafeInteger(value)) return null;
  // `-0` would otherwise survive as a distinct value.
  return value === 0 ? 0 : value;
}
