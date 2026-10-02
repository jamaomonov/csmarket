/**
 * Opening the kassa once, from the payment's own page: a top-up's
 * (`/account/balance/topups/{number}`) or an order's (`/orders/{number}`).
 *
 * On a phone the kassa's `https://` link opens the bank's app, not a page in this tab, and
 * no kassa brings the customer back. So the form (the top-up form, the buy panel) goes to
 * the payment's page first (`?go=1`), and that page opens the kassa. Whatever happens
 * next, the tab the customer returns to is their top-up or order, with its status and a
 * pay button.
 *
 * The flag must fire at most once, or coming back from the bank would throw the customer
 * straight back into it. Three guards, any one of which is enough: a `useRef` latch in the
 * component (re-renders, polls, StrictMode), a per-tab mark here (a reload, a restored
 * tab), and the flag stripped from the address (a new session, a bookmark). Marks are
 * keyed by number; top-up numbers (`T…`) and order numbers never collide.
 */

const GO_PARAM = "go";

/**
 * How long after arriving the page may still open the kassa by itself. Opening the bank
 * app only reads as the continuation of the customer's tap; ten seconds later, on a slow
 * connection, it is a hijack. Past this the page shows the button and the customer decides.
 */
export const AUTO_OPEN_BUDGET_MS = 8_000;
const GO_VALUE = "1";
const KEY_PREFIX = "csmarket.web.kassa_opened.";

// Where the mark lives when the browser refuses sessionStorage: this page load only.
const openedHere = new Set<string>();

function storedMark(number: string): boolean {
  try {
    return window.sessionStorage.getItem(`${KEY_PREFIX}${number}`) === GO_VALUE;
  } catch {
    // Private mode / storage blocked: opening once too often beats never opening.
    return false;
  }
}

/** Whether this page was asked (`?go=1`) to open the kassa and this tab has not yet. */
export function shouldAutoOpen(number: string, search: string): boolean {
  if (new URLSearchParams(search).get(GO_PARAM) !== GO_VALUE) return false;
  return !openedHere.has(number) && !storedMark(number);
}

/** Spend the one-shot for this top-up or order in this tab. Never throws. */
export function markOpened(number: string): void {
  openedHere.add(number);
  try {
    window.sessionStorage.setItem(`${KEY_PREFIX}${number}`, GO_VALUE);
  } catch {
    // The in-memory mark and the stripped address still hold.
  }
}

/** `search` without the one-shot flag: `"?mock=1&go=1"` → `"?mock=1"`, `"?go=1"` → `""`. */
export function searchWithoutGo(search: string): string {
  const params = new URLSearchParams(search);
  params.delete(GO_PARAM);
  const rest = params.toString();
  return rest === "" ? "" : `?${rest}`;
}
